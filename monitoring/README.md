# Monitoring

This directory contains the debug monitoring stack used by Docker Compose.

- Grafana reads dashboards and datasources from `grafana/provisioning`.
- Loki stores Docker container logs collected by Promtail.
- Prometheus stores container metrics scraped from cAdvisor.
- cAdvisor exposes per-container network packet and throughput metrics.
- `debug_network_exporter` exposes the current Docker containers attached to the `debug` network, plus packet-flow, received-packet, and connection metrics derived from `debug_packet_capture`.
- `debug_packet_capture` writes live tcpdump output to Docker logs, which Promtail ships to Loki and the exporter reuses to identify external peers as well as container-to-container traffic.

All debug services run on the external internal `debug` Docker network created by `setup.sh`. Nginx also joins that network and publishes Grafana at `/grafana/` through port `80`.

`setup.sh` creates the `debug` network with `172.24.0.0/16` by default so the packet capture filter can ignore debug monitoring traffic consistently. Override the subnet for new networks with `DEBUG_NETWORK_SUBNET`.

The packet capture service runs with host networking and `NET_ADMIN`/`NET_RAW` so it can see Docker bridge traffic. Tune capture volume with:

```env
PACKET_CAPTURE_INTERFACE=any
PACKET_CAPTURE_FILTER=((tcp or udp or icmp) and not net 172.24.0.0/16 and not port 3000 and not port 3100 and not port 9090 and not port 9080 and not port 8080)
```

The default filter excludes the `debug` network subnet and common monitoring ports so Grafana/Loki/Promtail/Prometheus/cAdvisor traffic does not dominate the packet trace. Grafana dashboard queries expose a `debug_container` selector for choosing which containers to monitor, while flow panels can now show external services by IP and port. Use a narrower filter in production-like environments to avoid high log volume.
