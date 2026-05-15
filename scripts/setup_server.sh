#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   MeshCompute Server Setup   ${NC}"
echo -e "${BLUE}========================================${NC}"

for cmd in git python3 openssl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo -e "${RED}Fehler: '$cmd' nicht installiert.${NC}"; exit 1
    fi
done

read -p "Öffentliche IP / Domain des Servers: " SERVER_HOST
SERVER_PORT=443
read -p "HTTPS-Port? [Standard: $SERVER_PORT]: " input_port
SERVER_PORT=${input_port:-$SERVER_PORT}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="$HOME/meshcompute-deploy"
echo -e "${GREEN}Repository: $REPO_DIR${NC}"
echo -e "${GREEN}Deployment-Ordner: $DEPLOY_DIR${NC}"

cd "$REPO_DIR"
pip3 install -r requirements.txt -q 2>/dev/null

# Secrets
AUTH_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(16))")
REGISTRATION_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(24))")
# Statische Bot-Secrets (optional, wenn du weiterhin manuelle Bots erlauben willst)
BOT_SECRET1=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRET2=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRET3=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRETS_JSON="{\"bot01\":\"$BOT_SECRET1\",\"bot02\":\"$BOT_SECRET2\",\"bot03\":\"$BOT_SECRET3\"}"

# Zertifikat
mkdir -p "$REPO_DIR/ssl"
openssl req -x509 -newkey rsa:4096 -keyout "$REPO_DIR/ssl/key.pem" -out "$REPO_DIR/ssl/cert.pem" \
    -days 365 -nodes -subj "/CN=${SERVER_HOST}" 2>/dev/null

# Deployment-Ordner
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"
cp -r "$REPO_DIR/server" "$DEPLOY_DIR/"
cp -r "$REPO_DIR/docker" "$DEPLOY_DIR/"
cp -r "$REPO_DIR/ssl" "$DEPLOY_DIR/"

# .env schreiben (direkt in docker/)
cat > "$DEPLOY_DIR/docker/.env" << EOF
AUTH_TOKEN=$AUTH_TOKEN
BOT_SECRETS='$BOT_SECRETS_JSON'
REDIS_URL=redis://redis:6379
REDIS_PASSWORD=$REDIS_PASSWORD
REGISTRATION_TOKEN=$REGISTRATION_TOKEN
SERVER_PORT=$SERVER_PORT
SERVER_HOST=$SERVER_HOST
TLS_CERT=/certs/cert.pem
TLS_KEY=/certs/key.pem
SERVER_URL=wss://${SERVER_HOST}:${SERVER_PORT}/ws
EOF

# docker-compose.yml überschreiben (sauberes Setup)
cat > "$DEPLOY_DIR/docker/docker-compose.yml" << 'YML'
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD:-redis_geheim}
    networks:
      - meshnet
    volumes:
      - redis_data:/data

  server:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    environment:
      AUTH_TOKEN: ${AUTH_TOKEN}
      BOT_SECRETS: ${BOT_SECRETS}
      REDIS_URL: redis:6379
      REDIS_PASSWORD: ${REDIS_PASSWORD:-redis_geheim}
      REGISTRATION_TOKEN: ${REGISTRATION_TOKEN}
      SERVER_PORT: "8080"
      TLS_CERT: ${TLS_CERT:-}
      TLS_KEY: ${TLS_KEY:-}
      SERVER_HOST: ${SERVER_HOST}
    ports:
      - "${SERVER_PORT:-443}:8080"
    volumes:
      - ../ssl:/certs:ro
    networks:
      - meshnet
    depends_on:
      - redis

volumes:
  redis_data:

networks:
  meshnet:
YML

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Server-Deployment fertig!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Kopiere den Ordner auf deinen Server:"
echo -e "  ${YELLOW}scp -r $DEPLOY_DIR kiwi@192.168.1.188:/home/kiwi${NC}"
echo ""
echo -e "Dann auf dem Server:"
echo -e "  ${YELLOW}cd ~/meshcompute-deploy/docker && docker compose up -d --build${NC}"
echo ""
echo -e "${RED}Wichtige Geheimnisse:${NC}"
echo -e "  AUTH_TOKEN:           $AUTH_TOKEN"
echo -e "  Redis-Passwort:       $REDIS_PASSWORD"
echo -e "  Registration Token:   $REGISTRATION_TOKEN"
echo -e "  Bot-Secrets (fest):"
echo -e "    bot01: $BOT_SECRET1"
echo -e "    bot02: $BOT_SECRET2"
echo -e "    bot03: $BOT_SECRET3"