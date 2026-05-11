# VPS Infra Base

Base de infraestrutura local com Nginx como proxy TCP, PostgreSQL, RabbitMQ e monitoramento de debug.

O objetivo deste projeto é fornecer uma stack simples para subir os serviços essenciais de uma aplicação em um servidor ou ambiente local, com portas e configurações padronizadas.

## Visão geral

O projeto sobe os seguintes serviços:

- Nginx para proxy TCP das conexões do RabbitMQ e do PostgreSQL.
- RabbitMQ com Management UI para filas, exchanges, usuários e permissões.
- PostgreSQL com criação padrão via variáveis de ambiente.
- Grafana com Loki/Promtail para logs de containers.
- Prometheus com cAdvisor para pacotes e tráfego de rede dos containers.
- Exporter da rede `debug` para filtrar métricas apenas por containers conectados nessa rede.
- Captura de pacotes com tcpdump para visualizar origem, destino, protocolo e portas no Grafana.

## Arquitetura

### Portas expostas

- 80: Nginx.
- 6380: acesso TCP ao RabbitMQ através do proxy do Nginx.
- 5433: acesso TCP ao PostgreSQL através do proxy do Nginx.
- /grafana/: Grafana via Nginx para debug de logs e métricas dos containers.

### Fluxo de rede

As aplicações externas podem falar com o Nginx nas portas 6380 e 5433, e o Nginx encaminha para os containers internos:

- RabbitMQ em nginx_rabbitmq:5672.
- PostgreSQL em nginx_postgres:5432.

O monitoramento roda em uma rede Docker externa interna chamada `debug`. Essa rede isola o tráfego entre Grafana, Loki, Promtail, Prometheus e cAdvisor da rede de aplicação `nginx`, mas permite que outros projetos Docker Compose entrem nela explicitamente para expor logs e métricas ao debug. O Nginx também entra nessa rede para publicar apenas a rota `/grafana/`.

## Estrutura do projeto

- docker-compose.yml: define os serviços da stack.
- monitoring/: configura Grafana, Loki, Promtail, Prometheus e dashboards.
- nginx/nginx.conf: configuração do proxy TCP para RabbitMQ e PostgreSQL.
- rabbitmq/rabbitmq.conf: configurações básicas do broker RabbitMQ.
- setup.sh: cria as redes externas usadas pelo compose.
- .env.example: variáveis de ambiente de exemplo.

## Requisitos

- Docker e Docker Compose.
- Rede Docker externa chamada nginx.
- Rede Docker externa interna chamada debug.

Para criar as redes:

```bash
sh setup.sh
```

## Configuração

Copie o arquivo .env.example para .env e ajuste os valores conforme o ambiente.

Variáveis disponíveis:

- POSTGRES_USER: usuário inicial do PostgreSQL.
- POSTGRES_PASSWORD: senha do PostgreSQL.
- POSTGRES_DB: banco inicial.
- RABBITMQ_ADMIN_USER: usuário administrador do RabbitMQ.
- RABBITMQ_ADMIN_PASS: senha do administrador do RabbitMQ.
- RABBITMQ_DEFAULT_VHOST: vhost inicial do RabbitMQ.
- GRAFANA_ADMIN_USER: usuário administrador do Grafana.
- GRAFANA_ADMIN_PASSWORD: senha do administrador do Grafana.
- GRAFANA_ROOT_URL: URL pública do Grafana quando acessado via Nginx.
- DEBUG_NETWORK_SUBNET: subnet usada ao criar a rede externa interna `debug` no `setup.sh`.
- PACKET_CAPTURE_INTERFACE: interface usada pela captura de pacotes.
- PACKET_CAPTURE_FILTER: filtro tcpdump usado pela captura de pacotes.

## Como subir a stack

1. Crie a rede Docker, se ainda não existir.

```bash
sh setup.sh
```

2. Crie e ajuste o arquivo .env.

3. Suba os serviços essenciais.

```bash
make up
```

4. Verifique os containers.

```bash
docker compose ps
```

Para subir o stack de observabilidade/debug explicitamente:

```bash
make debug-up
```

## Acesso ao RabbitMQ

Abra a interface de administração em:

```text
http://localhost/rabbitmq/
```

Use as credenciais do admin definidas em .env.

## Acesso ao Grafana

Abra o painel em:

```text
http://localhost/grafana/
```

Use as credenciais `GRAFANA_ADMIN_USER` e `GRAFANA_ADMIN_PASSWORD` definidas em `.env`.

O Grafana já sobe com dois datasources provisionados:

- Loki: logs dos containers Docker coletados pelo Promtail.
- Prometheus: métricas do cAdvisor, incluindo pacotes e tráfego de rede por container.

O dashboard `Container Debug` é provisionado automaticamente com um card de containers da rede `debug` e com painéis de logs, pacotes de rede e throughput apenas dos containers conectados na rede `debug`, ocultando os containers internos `debug_*` usados pelo próprio monitoramento. Use o seletor `debug_container` no topo do dashboard para escolher quais containers quer monitorar.

O dashboard `Container Packet Trace` mostra grafos de fluxo origem -> destino, top fluxos dos ultimos 5 minutos e tambem mantem o stream bruto capturado pelo container `debug_packet_capture`. O filtro padrao ignora o trafego da rede `debug` e portas de monitoramento para evitar que Grafana, Loki, Promtail, Prometheus e cAdvisor dominem a visualizacao. Esse dashboard complementa o cAdvisor: o cAdvisor mostra volume por container; o tcpdump mostra o trafego observado no host.

### Criar usuários de aplicação

Os usuários de aplicação não são criados automaticamente. O fluxo esperado é:

1. Entrar na interface do RabbitMQ com o usuário admin.
2. Criar o novo usuário.
3. Definir as permissões no vhost desejado.

Isso pode ser feito sem reiniciar a aplicação ou o broker.

## PostgreSQL inicial

O PostgreSQL é inicializado apenas com as variáveis `POSTGRES_USER`, `POSTGRES_PASSWORD` e `POSTGRES_DB`, sem scripts adicionais de bootstrap.

Com isso, o usuário admin definido em `.env` é o único usuário criado automaticamente pela stack.

## RabbitMQ

O container usa a imagem rabbitmq:3-management-alpine e carrega a configuração em rabbitmq/rabbitmq.conf.

Configurações atuais:

- listener TCP padrão em 5672.
- Management UI em 15672.
- log em console habilitado.

O proxy Nginx expõe o RabbitMQ na porta 6380 para clientes TCP e também publica o painel web em /rabbitmq/.

## Observações

- O Nginx precisa da rede externa nginx para conseguir resolver os nomes dos containers.
- A rede debug é externa, interna e criada pelo `setup.sh`.
- O banco PostgreSQL está configurado para persistir dados em um volume nomeado.
- O projeto foi organizado para facilitar a expansão futura com novos serviços e ambientes.

## Próximos passos comuns

- Ajustar permissões e vhosts do RabbitMQ para cada aplicação.
- Criar um arquivo de produção separado para variáveis sensíveis.
- Adicionar alertas no Grafana para falhas de serviços e picos de tráfego.
- Adicionar backup do PostgreSQL.
