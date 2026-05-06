#!/usr/bin/env python3
import http.client
import json
import os
import socket
import urllib.parse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
NETWORK_NAME = os.getenv("DEBUG_NETWORK_NAME", "debug")
LISTEN_ADDR = os.getenv("NETWORK_EXPORTER_ADDR", "0.0.0.0")
LISTEN_PORT = int(os.getenv("NETWORK_EXPORTER_PORT", "9108"))
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")
FLOW_LOOKBACK = os.getenv("NETWORK_EXPORTER_FLOW_LOOKBACK", "30s")
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


def endpoint_label(name: str, ip: str, port: str) -> str:
    if name:
        return name
    if ip and port:
        return f"{ip}:{port}"
    return ip


def upstream_ip(value: str) -> str:
    if not value:
        return ""
    first = value.split(",", 1)[0].strip()
    host = first.rsplit(":", 1)[0] if ":" in first else first
    return ipv4_without_prefix(host)


def gateway_ips() -> set[str]:
    gateways = set()
    for network in docker_get("/networks"):
        network_name = network.get("Name", "")
        if not network_name:
            continue
        try:
            details = docker_get(f"/networks/{network_name}")
        except Exception:
            continue
        for config in (details.get("IPAM", {}).get("Config", []) or []):
            gateway = ipv4_without_prefix(config.get("Gateway", ""))
            if gateway:
                gateways.add(gateway)
    return gateways


def resolve_endpoint(ip: str, port: str, ip_to_name: dict[str, str]) -> dict[str, str]:
    name = ip_to_name.get(ip, "")
    return {
        "name": name,
        "label": endpoint_label(name, ip, port),
        "kind": "container" if name else "external",
        "ip": ip,
        "port": port,
    }


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
    blocked_gateway_ips = gateway_ips()
    container_names = {}
    ip_to_name = {}
    service_ports = {}
    external_nodes = set()

    lines = [
        "# HELP docker_container_network_info Docker container membership in a Docker network.",
        "# TYPE docker_container_network_info gauge",
        "# HELP docker_container_network_address_info Docker container IPv4 addresses across networks for containers in the debug network.",
        "# TYPE docker_container_network_address_info gauge",
        "# HELP docker_container_graph_node_info Docker container nodes for Grafana node graph.",
        "# TYPE docker_container_graph_node_info gauge",
        "# HELP docker_container_packet_flow_packets Packets observed between containers and external endpoints over the configured lookback.",
        "# TYPE docker_container_packet_flow_packets gauge",
        "# HELP docker_container_packet_direction_packets Directional packets observed between containers and external endpoints over the configured lookback.",
        "# TYPE docker_container_packet_direction_packets gauge",
        "# HELP docker_container_packet_sent_packets Packets sent by each container to each observed peer over the configured lookback.",
        "# TYPE docker_container_packet_sent_packets gauge",
        "# HELP docker_container_packet_received_packets Packets received by each container from each observed peer over the configured lookback.",
        "# TYPE docker_container_packet_received_packets gauge",
        "# HELP docker_container_communication_edge_packets Communication edges between containers and external peers over the configured lookback.",
        "# TYPE docker_container_communication_edge_packets gauge",
        "# HELP docker_container_communication_edge_http_requests HTTP requests observed for an edge over the configured lookback.",
        "# TYPE docker_container_communication_edge_http_requests gauge",
        "# HELP docker_container_communication_edge_tcp_connections Distinct TCP 5-tuples observed for an edge over the configured lookback.",
        "# TYPE docker_container_communication_edge_tcp_connections gauge",
        "# HELP docker_container_connection_active_count Distinct observed packet 5-tuples per container and peer over the configured lookback.",
        "# TYPE docker_container_connection_active_count gauge",
        "# HELP docker_container_connection_persistent_count Distinct observed packet 5-tuples seen more than once per container and peer over the configured lookback.",
        "# TYPE docker_container_connection_persistent_count gauge",
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
        "topk(%d, sum by (src_ip, src_port, dst_ip, dst_port) "
        '(count_over_time({container="debug_packet_capture", src_ip!="", dst_ip!=""}[%s])))'
    ) % (FLOW_LIMIT, FLOW_LOOKBACK)
    try:
        payload = http_get_json(f"{LOKI_URL}/loki/api/v1/query?{urllib.parse.urlencode({'query': query})}")
        http_query = (
            'sum by (upstream_addr) (count_over_time({container="nginx_proxy", event="nginx_access", upstream_addr!=""}[%s]))'
            % FLOW_LOOKBACK
        )
        http_payload = http_get_json(f"{LOKI_URL}/loki/api/v1/query?{urllib.parse.urlencode({'query': http_query})}")
        logical_flows = defaultdict(float)
        directional_flows = defaultdict(float)
        sent_packets = defaultdict(float)
        received_packets = defaultdict(float)
        container_sent_totals = defaultdict(float)
        container_received_totals = defaultdict(float)
        container_active_totals = defaultdict(set)
        container_persistent_totals = defaultdict(set)
        edge_packets = defaultdict(float)
        edge_tcp_connections = defaultdict(set)
        edge_http_requests = defaultdict(float)
        active_connections = defaultdict(set)
        persistent_connections = defaultdict(set)
        for result in payload.get("data", {}).get("result", []):
            metric = result.get("metric", {})
            value = float(result.get("value", [None, "0"])[1])
            src_ip = metric.get("src_ip", "")
            src_port = metric.get("src_port", "")
            dst_ip = metric.get("dst_ip", "")
            dst_port = metric.get("dst_port", "")
            if src_ip in blocked_gateway_ips or dst_ip in blocked_gateway_ips:
                continue
            src_endpoint = resolve_endpoint(src_ip, src_port, ip_to_name)
            dst_endpoint = resolve_endpoint(dst_ip, dst_port, ip_to_name)
            if src_endpoint["kind"] == "external":
                external_nodes.add(src_endpoint["label"])
            if dst_endpoint["kind"] == "external":
                external_nodes.add(dst_endpoint["label"])

            if src_endpoint["kind"] == "container" and dst_endpoint["kind"] == "container" and src_endpoint["name"] == dst_endpoint["name"]:
                continue

            if src_endpoint["kind"] == "container":
                container = src_endpoint["label"]
                peer = dst_endpoint["label"]
                peer_kind = dst_endpoint["kind"]
                sent_key = (container, peer, peer_kind, dst_endpoint["ip"], dst_endpoint["port"])
                sent_packets[sent_key] += value
                container_sent_totals[container] += value
                conn_key = (container, peer, peer_kind, "sent")
                connection_key = f"{src_ip}:{src_port or '0'}|{dst_ip}:{dst_port or '0'}"
                active_connections[conn_key].add(connection_key)
                container_active_totals[container].add(connection_key)
                if value > 1:
                    persistent_connections[conn_key].add(connection_key)
                    container_persistent_totals[container].add(connection_key)

            if dst_endpoint["kind"] == "container":
                container = dst_endpoint["label"]
                peer = src_endpoint["label"]
                peer_kind = src_endpoint["kind"]
                received_key = (container, peer, peer_kind, src_endpoint["ip"], src_endpoint["port"])
                received_packets[received_key] += value
                container_received_totals[container] += value
                conn_key = (container, peer, peer_kind, "received")
                connection_key = f"{src_ip}:{src_port or '0'}|{dst_ip}:{dst_port or '0'}"
                active_connections[conn_key].add(connection_key)
                container_active_totals[container].add(connection_key)
                if value > 1:
                    persistent_connections[conn_key].add(connection_key)
                    container_persistent_totals[container].add(connection_key)

            sender = src_endpoint["name"] or src_endpoint["ip"]
            receiver = dst_endpoint["name"] or dst_endpoint["ip"]
            if src_endpoint["kind"] == "external" and dst_endpoint["kind"] == "external":
                continue
            source, target = logical_direction(sender, receiver, src_port, dst_port, service_ports)
            if source == sender:
                flow_src_ip, flow_src_port, flow_dst_ip, flow_dst_port = src_ip, src_port, dst_ip, dst_port
            else:
                flow_src_ip, flow_src_port, flow_dst_ip, flow_dst_port = dst_ip, dst_port, src_ip, src_port
            flow_key = (source, target, flow_src_ip, flow_src_port, flow_dst_ip, flow_dst_port)
            logical_flows[flow_key] += value
            directional_key = (sender, receiver, src_ip, src_port, dst_ip, dst_port)
            directional_flows[directional_key] += value
            edge_key = (source, target)
            edge_packets[edge_key] += value
            edge_tcp_connections[edge_key].add(flow_key)

        for result in http_payload.get("data", {}).get("result", []):
            metric = result.get("metric", {})
            upstream_addr = metric.get("upstream_addr", "")
            value = float(result.get("value", [None, "0"])[1])
            target_ip = upstream_ip(upstream_addr)
            if not target_ip:
                continue
            target_endpoint = resolve_endpoint(target_ip, "", ip_to_name)
            source = "nginx_proxy"
            target = target_endpoint["label"]
            edge_http_requests[(source, target)] += value

        for container in sorted(container_names):
            sent_total = int(container_sent_totals.get(container, 0))
            received_total = int(container_received_totals.get(container, 0))
            active_total = int(len(container_active_totals.get(container, set())))
            persistent_total = int(len(container_persistent_totals.get(container, set())))
            lines.append(
                'docker_container_graph_node_info{id="%s",title="%s",subtitle="%s",mainstat="%s",secondarystat="%s",detail__sent_packets="%s",detail__received_packets="%s",detail__active_connections="%s",detail__persistent_connections="%s"} 25'
                % (
                    escape_label(container),
                    escape_label(container),
                    escape_label(NETWORK_NAME),
                    sent_total + received_total,
                    active_total,
                    sent_total,
                    received_total,
                    active_total,
                    persistent_total,
                )
            )

        for (source, target, src_ip, src_port, dst_ip, dst_port), value in sorted(logical_flows.items(), key=lambda item: item[1], reverse=True)[:FLOW_LIMIT]:
            edge_id = f"{source}->{target}"
            lines.append(
                'docker_container_packet_flow_packets{id="%s",source="%s",target="%s",src_ip="%s",src_port="%s",dst_ip="%s",dst_port="%s"} %s'
                % (
                    escape_label(edge_id),
                    escape_label(source),
                    escape_label(target),
                    escape_label(src_ip),
                    escape_label(src_port),
                    escape_label(dst_ip),
                    escape_label(dst_port),
                    int(value),
                )
            )

        edge_keys = set(edge_packets) | set(edge_http_requests)
        ordered_edges = sorted(
            edge_keys,
            key=lambda edge: edge_packets.get(edge, 0) + edge_http_requests.get(edge, 0),
            reverse=True,
        )[:FLOW_LIMIT]
        for source, target in ordered_edges:
            packet_count = edge_packets.get((source, target), 0)
            http_requests = edge_http_requests.get((source, target), 0)
            tcp_connections = len(edge_tcp_connections.get((source, target), set()))
            edge_id = f"{source}->{target}"
            lines.append(
                'docker_container_communication_edge_packets{id="%s",source="%s",target="%s"} %s'
                % (
                    escape_label(edge_id),
                    escape_label(source),
                    escape_label(target),
                    int(packet_count + http_requests),
                )
            )
            lines.append(
                'docker_container_communication_edge_http_requests{id="%s",source="%s",target="%s"} %s'
                % (
                    escape_label(edge_id),
                    escape_label(source),
                    escape_label(target),
                    int(http_requests),
                )
            )
            lines.append(
                'docker_container_communication_edge_tcp_connections{id="%s",source="%s",target="%s"} %s'
                % (
                    escape_label(edge_id),
                    escape_label(source),
                    escape_label(target),
                    tcp_connections,
                )
            )

        for (sender, receiver, src_ip, src_port, dst_ip, dst_port), value in sorted(directional_flows.items(), key=lambda item: item[1], reverse=True)[:FLOW_LIMIT]:
            lines.append(
                'docker_container_packet_direction_packets{sender="%s",receiver="%s",src_ip="%s",src_port="%s",dst_ip="%s",dst_port="%s"} %s'
                % (
                    escape_label(sender),
                    escape_label(receiver),
                    escape_label(src_ip),
                    escape_label(src_port),
                    escape_label(dst_ip),
                    escape_label(dst_port),
                    int(value),
                )
            )

        for (container, peer, peer_kind, peer_ip, peer_port), value in sorted(sent_packets.items()):
            lines.append(
                'docker_container_packet_sent_packets{container="%s",peer="%s",peer_kind="%s",peer_ip="%s",peer_port="%s"} %s'
                % (
                    escape_label(container),
                    escape_label(peer),
                    escape_label(peer_kind),
                    escape_label(peer_ip),
                    escape_label(peer_port),
                    int(value),
                )
            )

        for (container, peer, peer_kind, peer_ip, peer_port), value in sorted(received_packets.items()):
            lines.append(
                'docker_container_packet_received_packets{container="%s",peer="%s",peer_kind="%s",peer_ip="%s",peer_port="%s"} %s'
                % (
                    escape_label(container),
                    escape_label(peer),
                    escape_label(peer_kind),
                    escape_label(peer_ip),
                    escape_label(peer_port),
                    int(value),
                )
            )

        for (container, peer, peer_kind, direction), signatures in sorted(active_connections.items()):
            lines.append(
                'docker_container_connection_active_count{container="%s",peer="%s",peer_kind="%s",direction="%s"} %s'
                % (
                    escape_label(container),
                    escape_label(peer),
                    escape_label(peer_kind),
                    escape_label(direction),
                    len(signatures),
                )
            )

        for (container, peer, peer_kind, direction), signatures in sorted(persistent_connections.items()):
            lines.append(
                'docker_container_connection_persistent_count{container="%s",peer="%s",peer_kind="%s",direction="%s"} %s'
                % (
                    escape_label(container),
                    escape_label(peer),
                    escape_label(peer_kind),
                    escape_label(direction),
                    len(signatures),
                )
            )

        for node in sorted(external_nodes):
            lines.append(
                'docker_container_graph_node_info{id="%s",title="%s",subtitle="%s"} 25'
                % (escape_label(node), escape_label(node), escape_label("external"))
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
