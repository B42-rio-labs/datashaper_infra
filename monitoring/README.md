# Monitoring

This directory contains the debug monitoring stack used by Docker Compose.

- Grafana reads dashboards and datasources from `grafana/provisioning`.
- Loki stores Docker container logs collected by Promtail.
- Prometheus stores container metrics scraped from cAdvisor.
- cAdvisor exposes per-container network packet and throughput metrics.

All debug services run on the external internal `debug` Docker network created by `setup.sh`. Nginx also joins that network and publishes Grafana at `/grafana/` through port `80`.
