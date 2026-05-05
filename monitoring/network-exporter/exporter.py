#!/usr/bin/env python3
import http.client
import json
import os
import socket
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
NETWORK_NAME = os.getenv("DEBUG_NETWORK_NAME", "debug")
LISTEN_ADDR = os.getenv("NETWORK_EXPORTER_ADDR", "0.0.0.0")
LISTEN_PORT = int(os.getenv("NETWORK_EXPORTER_PORT", "9108"))
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")
FLOW_LOOKBACK = os.getenv("NETWORK_EXPORTER_FLOW_LOOKBACK", "15m")
FLOW_LIMIT = int(os.getenv("NETWORK_EXPORTER_FLOW_LIMIT", "50"))
EPHEMERAL_PORT_START = int(os.getenv("NETWORK_EXPORTER_EPHEMERAL_PORT_START", "32768"))


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)


def docker_get(path: str) -> dict:
    connection = UnixSocketHTTPConnection(DOCKER_SOCKET)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status >= 400:
            raise RuntimeError(f"Docker API returned {response.status}: {body.decode('utf-8', 'replace')}")
        return json.loads(body)
    finally:
        connection.close()


def http_get_json(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=3)
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {body.decode('utf-8', 'replace')}")
        return json.loads(body)
    finally:
        connection.close()


def escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def ipv4_without_prefix(value: str) -> str:
    return value.split("/", 1)[0] if value else ""


def port_number(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def exposed_ports(details: dict) -> set[int]:
    ports = set()
    for port_proto in details.get("Config", {}).get("ExposedPorts", {}) or {}:
        port = port_number(port_proto.split("/", 1)[0])
        if port:
            ports.add(port)
    return ports


def is_service_side(port: int, known_ports: set[int]) -> bool:
    return port in known_ports or (0 < port < EPHEMERAL_PORT_START)


def logical_direction(src_name: str, dst_name: str, src_port: str, dst_port: str, service_ports: dict[str, set[int]]) -> tuple[str, str]:
    if src_name == "nginx_proxy" and dst_name != "nginx_proxy":
        return src_name, dst_name
    if dst_name == "nginx_proxy" and src_name != "nginx_proxy":
        return dst_name, src_name

    src_port_number = port_number(src_port)
    dst_port_number = port_number(dst_port)
    src_is_service = is_service_side(src_port_number, service_ports.get(src_name, set()))
    dst_is_service = is_service_side(dst_port_number, service_ports.get(dst_name, set()))

    if src_is_service and not dst_is_service:
        return dst_name, src_name
    return src_name, dst_name


def collect_metrics() -> str:
    network = docker_get(f"/networks/{NETWORK_NAME}")
    containers = network.get("Containers") or {}
    container_names = {}
    ip_to_name = {}
    service_ports = {}

    lines = [
        "# HELP docker_container_network_info Docker container membership in a Docker network.",
        "# TYPE docker_container_network_info gauge",
        "# HELP docker_container_network_address_info Docker container IPv4 addresses across networks for containers in the debug network.",
        "# TYPE docker_container_network_address_info gauge",
        "# HELP docker_container_graph_node_info Docker container nodes for Grafana node graph.",
        "# TYPE docker_container_graph_node_info gauge",
        "# HELP docker_container_packet_flow_packets Packets observed between containers or endpoints over the configured lookback.",
        "# TYPE docker_container_packet_flow_packets gauge",
        "# HELP docker_container_packet_direction_packets Directional packets actually sent by each container over the configured lookback.",
        "# TYPE docker_container_packet_direction_packets gauge",
    ]

    for container_id, container in sorted(containers.items(), key=lambda item: item[1].get("Name", "")):
        name = container.get("Name", "")
        if not name:
            continue
        container_names[name] = name
        ipv4 = ipv4_without_prefix(container.get("IPv4Address", ""))
        lines.append(
            'docker_container_network_info{id="%s",name="%s",network="%s",ipv4="%s"} 1'
            % (escape_label(container_id), escape_label(name), escape_label(NETWORK_NAME), escape_label(ipv4))
        )
        lines.append(
            'docker_container_graph_node_info{id="%s",title="%s",subtitle="%s"} 1'
            % (escape_label(name), escape_label(name), escape_label(NETWORK_NAME))
        )
        details = docker_get(f"/containers/{container_id}/json")
        service_ports[name] = exposed_ports(details)
        networks = details.get("NetworkSettings", {}).get("Networks", {})
        for network_name, network_details in sorted(networks.items()):
            network_ipv4 = ipv4_without_prefix(network_details.get("IPAddress", ""))
            if not network_ipv4:
                continue
            ip_to_name[network_ipv4] = name
            lines.append(
                'docker_container_network_address_info{id="%s",name="%s",network="%s",ipv4="%s"} 1'
                % (
                    escape_label(container_id),
                    escape_label(name),
                    escape_label(network_name),
                    escape_label(network_ipv4),
                )
            )

    query = (
        "topk(%d, sum by (src_ip, dst_ip) "
        '(count_over_time({container="debug_packet_capture", src_ip!="", dst_ip!=""}[%s])))'
    ) % (FLOW_LIMIT, FLOW_LOOKBACK)
    try:
        payload = http_get_json(f"{LOKI_URL}/loki/api/v1/query?{urllib.parse.urlencode({'query': query})}")
        logical_flows = {}
        directional_flows = {}
        for result in payload.get("data", {}).get("result", []):
            metric = result.get("metric", {})
            value = float(result.get("value", [None, "0"])[1])
            src_ip = metric.get("src_ip", "")
            dst_ip = metric.get("dst_ip", "")
            src_port = metric.get("src_port", "")
            dst_port = metric.get("dst_port", "")
            sender = ip_to_name.get(src_ip, src_ip)
            receiver = ip_to_name.get(dst_ip, dst_ip)
            if sender == receiver:
                continue
            if sender not in container_names or receiver not in container_names:
                continue
            source, target = logical_direction(sender, receiver, src_port, dst_port, service_ports)
            if source == sender:
                flow_src_ip, flow_dst_ip = src_ip, dst_ip
            else:
                flow_src_ip, flow_dst_ip = dst_ip, src_ip
            flow_key = (source, target, flow_src_ip, flow_dst_ip)
            logical_flows[flow_key] = logical_flows.get(flow_key, 0.0) + value
            directional_key = (sender, receiver, src_ip, dst_ip)
            directional_flows[directional_key] = directional_flows.get(directional_key, 0.0) + value

        for (source, target, src_ip, dst_ip), value in logical_flows.items():
            edge_id = f"{source}->{target}"
            lines.append(
                'docker_container_packet_flow_packets{id="%s",source="%s",target="%s",src_ip="%s",dst_ip="%s"} %s'
                % (
                    escape_label(edge_id),
                    escape_label(source),
                    escape_label(target),
                    escape_label(src_ip),
                    escape_label(dst_ip),
                    int(value),
                )
            )

        for (sender, receiver, src_ip, dst_ip), value in directional_flows.items():
            lines.append(
                'docker_container_packet_direction_packets{sender="%s",receiver="%s",src_ip="%s",dst_ip="%s"} %s'
                % (
                    escape_label(sender),
                    escape_label(receiver),
                    escape_label(src_ip),
                    escape_label(dst_ip),
                    int(value),
                )
            )
    except Exception as exc:
        lines.append(f'# ERROR collecting packet flows from Loki: {escape_label(str(exc))}')

    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/metrics"):
            self.send_error(404)
            return

        try:
            payload = collect_metrics().encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            payload = f"# ERROR {exc}\n".encode("utf-8")
            self.send_response(500)

        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((LISTEN_ADDR, LISTEN_PORT), MetricsHandler)
    server.serve_forever()
