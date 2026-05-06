# Repository Guidelines

## Project Structure & Module Organization

This repository defines a Docker Compose infrastructure stack. `docker-compose.yml` is the main entry point; configuration is split by component:

- `nginx/`: reverse proxy, TCP proxy, and fallback error pages.
- `rabbitmq/`: RabbitMQ broker configuration.
- `monitoring/`: Grafana, Loki, Promtail, Prometheus, cAdvisor, packet capture, and `network-exporter`.
- `sql_script/`: database helper scripts.
- `.github/workflows/`: CI smoke test and VPS deployment.

There is no application source tree or formal test directory; validation is Compose- and service-focused.

## Build, Test, and Development Commands

- `cp .env.example .env`: create local environment variables before running Compose.
- `sh setup.sh`: create the external Docker networks `nginx` and internal `debug`.
- `docker compose config`: validate Compose syntax and resolved values.
- `docker compose up -d`: start the full stack locally.
- `docker compose up -d postgres rabbitmq`: start the services used by CI smoke tests.
- `docker compose ps`: inspect service status and health checks.
- `docker compose logs <service>`: debug a specific service, for example `docker compose logs nginx`.
- `docker compose down`: stop and remove containers while keeping named volumes.

## Coding Style & Naming Conventions

Use two-space indentation in YAML. Keep Compose service names lowercase with underscores when needed, matching `network_exporter` and `packet_capture`. Container names use `nginx_` and `debug_`.

Shell scripts should be POSIX-compatible `sh`, start with `#!/bin/sh`, and use `set -eu`. Mount configuration read-only when containers do not need to mutate it.

## Testing Guidelines

Run `docker compose config` before submitting changes. For service changes, run the CI-equivalent smoke test:

```bash
cp .env.example .env
sh setup.sh
docker compose up -d postgres rabbitmq
docker compose ps
docker compose down
```

Confirm PostgreSQL and RabbitMQ show healthy status. For nginx changes, start the stack and check proxied paths such as `/grafana/` and `/rabbitmq/`.

## Commit & Pull Request Guidelines

Git history uses short imperative summaries, sometimes with Conventional Commit prefixes, for example `fix: replace open-redirect...` or `Add Grafana container debug monitoring`. Prefer `fix:`, `feat:`, or `refactor:` when they clarify intent.

Pull requests should describe infrastructure impact, list changed services, include validation commands run, and mention required `.env` or secret changes. Attach screenshots only for Grafana dashboard or UI route changes.

## Security & Configuration Tips

Do not commit real `.env` secrets. Keep `.env.example` generic. Review nginx redirects, exposed ports, Docker socket mounts, privileged containers, and packet-capture filters because they affect host and network security.
