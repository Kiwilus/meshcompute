#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE} MeshCompute Server Setup ${NC}"
echo -e "${BLUE}========================================${NC}"

# Abhängigkeiten prüfen
for cmd in git python3 openssl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo -e "${RED}Fehler: '$cmd' nicht installiert.${NC}"
        exit 1
    fi
done

# Eingaben abfragen
read -r -p "Öffentliche IP / Domain des Servers: " SERVER_HOST
if [[ -z "$SERVER_HOST" ]]; then
    echo -e "${RED}Fehler: Server-Host darf nicht leer sein.${NC}"
    exit 1
fi

SERVER_PORT=443
read -r -p "HTTPS-Port? [Standard: $SERVER_PORT]: " input_port
SERVER_PORT="${input_port:-$SERVER_PORT}"

# Verzeichnisse ermitteln
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="$HOME/meshcompute-deploy"

echo -e "${GREEN}Repository: $REPO_DIR${NC}"
echo -e "${GREEN}Deployment-Ordner: $DEPLOY_DIR${NC}"

# In Repository wechseln und Abhängigkeiten installieren
cd "$REPO_DIR"
pip3 install -r requirements.txt || {
    echo -e "${RED}Fehler bei pip3 install${NC}"
    exit 1
}

# Secrets generieren
AUTH_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(16))")
REGISTRATION_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(24))")

# Bot-Secrets (statisch)
BOT_SECRET1=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRET2=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRET3=$(python3 -c "import secrets; print(secrets.token_hex(16))")

# JSON für Bot-Secrets (ohne äußere Anführungszeichen)
BOT_SECRETS_JSON="{\"bot01\":\"$BOT_SECRET1\",\"bot02\":\"$BOT_SECRET2\",\"bot03\":\"$BOT_SECRET3\"}"

# SSL-Zertifikat erstellen
mkdir -p "$REPO_DIR/ssl"
openssl req -x509 -newkey rsa:4096 \
    -keyout "$REPO_DIR/ssl/key.pem" \
    -out "$REPO_DIR/ssl/cert.pem" \
    -days 365 -nodes \
    -subj "/CN=${SERVER_HOST}" 2>/dev/null || {
        echo -e "${RED}Fehler beim Erstellen des Zertifikats.${NC}"
        exit 1
    }

# Deployment-Ordner vorbereiten
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# Benötigte Verzeichnisse kopieren (nur falls vorhanden)
for dir in server docker ssl; do
    if [ -d "$REPO_DIR/$dir" ]; then
        cp -r "$REPO_DIR/$dir" "$DEPLOY_DIR/"
    else
        echo -e "${YELLOW}Warnung: $REPO_DIR/$dir existiert nicht – wird übersprungen.${NC}"
    fi
done

# .env schreiben (ohne Anführungszeichen um BOT_SECRETS)
cat > "$DEPLOY_DIR/docker/.env" << EOF
AUTH_TOKEN=$AUTH_TOKEN
BOT_SECRETS=$BOT_SECRETS_JSON
REDIS_URL=redis://redis:6379
REDIS_PASSWORD=$REDIS_PASSWORD
REGISTRATION_TOKEN=$REGISTRATION_TOKEN
SERVER_PORT=$SERVER_PORT
SERVER_HOST=$SERVER_HOST
TLS_CERT=/certs/cert.pem
TLS_KEY=/certs/key.pem
SERVER_URL=wss://${SERVER_HOST}:${SERVER_PORT}/ws
EOF

# docker-compose.yml (ohne veraltete 'version')
cat > "$DEPLOY_DIR/docker/docker-compose.yml" << 'YML'
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
echo -e "${GREEN} Server-Deployment fertig!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# SCP-Befehl mit Platzhaltern (vom Benutzer anzupassen)
echo -e "Kopieren Sie den Ordner auf Ihren Server (ersetzen Sie USER und IP):"
echo -e " ${YELLOW}scp -r \"$DEPLOY_DIR\" USER@IHRE_SERVER_IP:/home/USER${NC}"
echo ""
echo -e "Dann auf dem Server:"
echo -e " ${YELLOW}cd ~/meshcompute-deploy/docker && docker compose up -d --build${NC}"
echo ""
echo -e "${RED}Wichtige Geheimnisse:${NC}"
echo -e " AUTH_TOKEN: $AUTH_TOKEN"
echo -e " Redis-Passwort: $REDIS_PASSWORD"
echo -e " Registration Token: $REGISTRATION_TOKEN"
echo -e " Bot-Secrets (fest):"
echo -e " bot01: $BOT_SECRET1"
echo -e " bot02: $BOT_SECRET2"
echo -e " bot03: $BOT_SECRET3"