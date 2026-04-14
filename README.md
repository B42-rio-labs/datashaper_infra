# VPS Infra Base

Base de infraestrutura local com Nginx como proxy TCP, PostgreSQL e RabbitMQ.

O objetivo deste projeto é fornecer uma stack simples para subir os serviços essenciais de uma aplicação em um servidor ou ambiente local, com portas e configurações padronizadas.

## Visão geral

O projeto sobe os seguintes serviços:

- Nginx para proxy TCP das conexões do RabbitMQ e do PostgreSQL.
- RabbitMQ com Management UI para filas, exchanges, usuários e permissões.
- PostgreSQL com banco inicial e script de bootstrap.

## Arquitetura

### Portas expostas

- 80: Nginx.
- 6380: acesso TCP ao RabbitMQ através do proxy do Nginx.
- 5433: acesso TCP ao PostgreSQL através do proxy do Nginx.

### Fluxo de rede

As aplicações externas podem falar com o Nginx nas portas 6380 e 5433, e o Nginx encaminha para os containers internos:

- RabbitMQ em nginx_rabbitmq:5672.
- PostgreSQL em nginx_postgres:5432.

## Estrutura do projeto

- docker-compose.yml: define os serviços da stack.
- nginx/nginx.conf: configuração do proxy TCP para RabbitMQ e PostgreSQL.
- rabbitmq/rabbitmq.conf: configurações básicas do broker RabbitMQ.
- init/init.sql: script inicial do PostgreSQL.
- setup.sh: cria a rede externa usada pelo compose.
- .env.example: variáveis de ambiente de exemplo.

## Requisitos

- Docker e Docker Compose.
- Rede Docker externa chamada nginx.

Para criar a rede:

```bash
docker network create nginx
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

## Como subir a stack

1. Crie a rede Docker, se ainda não existir.

```bash
sh setup.sh
```

2. Crie e ajuste o arquivo .env.

3. Suba os serviços.

```bash
docker compose up -d
```

4. Verifique os containers.

```bash
docker compose ps
```

## Acesso ao RabbitMQ

Abra a interface de administração em:

```text
http://localhost/rabbitmq/
```

Use as credenciais do admin definidas em .env.

### Criar usuários de aplicação

Os usuários de aplicação não são criados automaticamente. O fluxo esperado é:

1. Entrar na interface do RabbitMQ com o usuário admin.
2. Criar o novo usuário.
3. Definir as permissões no vhost desejado.

Isso pode ser feito sem reiniciar a aplicação ou o broker.

## PostgreSQL inicial

O diretório init contém o script que cria o banco, o usuário e as permissões iniciais.

Se o volume postgres_data já existir, o script de inicialização pode não rodar novamente. Nesse caso, recrie o volume ou aplique as alterações manualmente.

## RabbitMQ

O container usa a imagem rabbitmq:3-management-alpine e carrega a configuração em rabbitmq/rabbitmq.conf.

Configurações atuais:

- listener TCP padrão em 5672.
- Management UI em 15672.
- log em console habilitado.

O proxy Nginx expõe o RabbitMQ na porta 6380 para clientes TCP e também publica o painel web em /rabbitmq/.

## Observações

- O Nginx precisa da rede externa nginx para conseguir resolver os nomes dos containers.
- O banco PostgreSQL está configurado para persistir dados em um volume nomeado.
- O projeto foi organizado para facilitar a expansão futura com novos serviços e ambientes.

## Próximos passos comuns

- Ajustar permissões e vhosts do RabbitMQ para cada aplicação.
- Criar um arquivo de produção separado para variáveis sensíveis.
- Adicionar monitoramento e backup do PostgreSQL.