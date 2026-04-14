#!/bin/bash

CONTAINER_NAME="nginx_postgres"

# ===== INPUT =====
read -p "Nome do banco (DB_NAME): " DB_NAME
read -p "Usuário do banco (DB_USER): " DB_USER

printf "Senha do usuário (DB_PASS): "
stty -echo
read DB_PASS
stty echo
echo ""

read -p "Usuário admin do Postgres [postgres]: " POSTGRES_SUPERUSER
POSTGRES_SUPERUSER=${POSTGRES_SUPERUSER:-postgres}

# ===== VALIDAÇÃO =====
if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASS" ]; then
  echo "❌ Campos obrigatórios não preenchidos."
  exit 1
fi

echo "🚀 Configurando banco no container $CONTAINER_NAME..."

# ===== 1. CRIAR USUÁRIO =====
docker exec -i $CONTAINER_NAME psql -U $POSTGRES_SUPERUSER -d postgres <<EOF
DO \$\$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER'
   ) THEN
      EXECUTE format('CREATE USER %I WITH PASSWORD %L', '$DB_USER', '$DB_PASS');
   END IF;
END
\$\$;
EOF

# ===== 2. VERIFICAR SE DB EXISTE =====
DB_EXISTS=$(docker exec -i $CONTAINER_NAME psql -U $POSTGRES_SUPERUSER -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")

# ===== 3. CRIAR DATABASE SE NECESSÁRIO =====
if [ "$DB_EXISTS" != "1" ]; then
  echo "📦 Criando database $DB_NAME..."
  docker exec -i $CONTAINER_NAME psql -U $POSTGRES_SUPERUSER -d postgres -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\";"
else
  echo "ℹ️ Database $DB_NAME já existe."
fi

# ===== 4. PERMISSÕES =====
docker exec -i $CONTAINER_NAME psql -U $POSTGRES_SUPERUSER -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE \"$DB_NAME\" TO \"$DB_USER\";"

# ===== RESULTADO =====
if [ $? -eq 0 ]; then
  echo "✅ Banco e usuário configurados com sucesso!"
else
  echo "❌ Erro durante execução."
fi
