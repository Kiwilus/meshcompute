#!/usr/bin/env bash
set -euo pipefail

# Farben
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   MeshCompute Server Setup${NC}"
echo -e "${BLUE}========================================${NC}"

# Prüfen, ob nötige Programme da sind
if ! command -v git &>/dev/null || ! command -v python3 &>/dev/null || ! command -v openssl &>/dev/null; then
    echo -e "${RED}Fehler: Bitte installiere zuerst: git, python3, openssl${NC}"
    exit 1
fi

# Fragen
read -p "Öffentliche IP / Domain des Servers (z.B. mein-server.de): " SERVER_HOST
SERVER_PORT=443
read -p "HTTPS-Port? [Standard: 443]: " input_port
SERVER_PORT=${input_port:-$SERVER_PORT}

REPO_URL="https://github.com/Kiwilus/meshcompute.git"
WORKDIR="$(pwd)/meshcompute"

# Repository klonen, falls nicht vorhanden
if [ ! -d "$WORKDIR" ]; then
    echo -e "${GREEN}Klone Repository...${NC}"
    git clone "$REPO_URL" "$WORKDIR"
fi
cd "$WORKDIR"

# Python-Abhängigkeiten für den Generator
pip3 install -r requirements.txt -q 2>/dev/null

# Zufällige Secrets generieren
AUTH_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRET1=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRET2=$(python3 -c "import secrets; print(secrets.token_hex(16))")
BOT_SECRET3=$(python3 -c "import secrets; print(secrets.token_hex(16))")

BOT_SECRETS_JSON="{\"bot01\":\"$BOT_SECRET1\",\"bot02\":\"$BOT_SECRET2\",\"bot03\":\"$BOT_SECRET3\"}"

# TLS-Zertifikat generieren
mkdir -p ssl
openssl req -x509 -newkey rsa:4096 -keyout ssl/key.pem -out ssl/cert.pem -days 365 -nodes \
    -subj "/CN=${SERVER_HOST}" 2>/dev/null

# .env Datei schreiben
cat > .env << EOF
AUTH_TOKEN=$AUTH_TOKEN
BOT_SECRETS='$BOT_SECRETS_JSON'
REDIS_URL=redis://redis:6379
REDIS_PASSWORD=$REDIS_PASSWORD
SERVER_PORT=$SERVER_PORT
SERVER_HOST=$SERVER_HOST
TLS_CERT=/certs/cert.pem
TLS_KEY=/certs/key.pem
SERVER_URL=wss://${SERVER_HOST}:${SERVER_PORT}/ws
EOF

# Deployment-Ordner vorbereiten
DEPLOY_DIR="$WORKDIR/../meshcompute-deploy"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# Notwendige Dateien kopieren
cp -r "$WORKDIR/server" "$DEPLOY_DIR/"
cp -r "$WORKDIR/docker" "$DEPLOY_DIR/"
cp "$WORKDIR/.env" "$DEPLOY_DIR/"
cp -r "$WORKDIR/ssl" "$DEPLOY_DIR/"

# docker-compose.yml anpassen, damit TLS und Volumes eingebunden werden
cd "$DEPLOY_DIR/docker"
# Füge TLS-Umgebungsvariablen und Volume in docker-compose.yml ein
if ! grep -q "TLS_CERT" docker-compose.yml; then
    cp docker-compose.yml docker-compose.yml.bak
    sed -i '/REDIS_PASSWORD:.*/a\      TLS_CERT: ${TLS_CERT:-}\n      TLS_KEY: ${TLS_KEY:-}\n      SERVER_HOST: ${SERVER_HOST}' docker-compose.yml
    sed -i '/depends_on:/i\    volumes:\n      - ../ssl:/certs:ro' docker-compose.yml
fi

cd "$DEPLOY_DIR"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Server-Deployment vorbereitet!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Deployment-Ordner: ${YELLOW}$DEPLOY_DIR${NC}"
echo -e "Kopiere diesen Ordner auf deinen Server, z.B.:"
echo -e "  ${YELLOW}scp -r $DEPLOY_DIR nutzer@dein-server:~/meshcompute-deploy${NC}"
echo ""
echo -e "Dann auf dem Server:"
echo -e "  ${YELLOW}cd ~/meshcompute-deploy/docker && docker compose up -d${NC}"
echo ""
echo -e "${RED}Wichtige Secrets (bitte sicher aufbewahren):${NC}"
echo -e "  AUTH_TOKEN:        $AUTH_TOKEN"
echo -e "  Redis-Passwort:    $REDIS_PASSWORD"
echo -e "  Bot-Secrets:"
echo -e "    bot01: $BOT_SECRET1"
echo -e "    bot02: $BOT_SECRET2"
echo -e "    bot03: $BOT_SECRET3"