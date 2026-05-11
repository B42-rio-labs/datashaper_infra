COMPOSE ?= docker compose
CORE_SERVICES ?= nginx rabbitmq postgres
DEBUG_SERVICES ?= grafana loki promtail prometheus cadvisor network_exporter packet_capture

.PHONY: up debug-up down ps logs config

up:
	$(COMPOSE) up -d --no-deps $(CORE_SERVICES)

debug-up:
	$(COMPOSE) up -d $(DEBUG_SERVICES)

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

config:
	$(COMPOSE) config
