#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}MeshCompute Controller Setup${NC}"

# Abhängigkeiten prüfen
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Python3 ist nicht installiert.${NC}"
    exit 1
fi

read -p "Server-URL (z.B. wss://mein-server.de:443/ws): " SERVER_URL
read -p "AUTH_TOKEN: " AUTH_TOKEN

REPO_URL="https://github.com/Kiwilus/meshcompute.git"
CONTROLLER_DIR="$(pwd)/meshcompute-controller"

if [ ! -d "$CONTROLLER_DIR" ]; then
    git clone "$REPO_URL" "$CONTROLLER_DIR"
fi
cd "$CONTROLLER_DIR"

pip3 install -r requirements.txt -q

# .env für den Controller anlegen
cat > .env << EOF
AUTH_TOKEN=$AUTH_TOKEN
SERVER_URL=$SERVER_URL
EOF

echo ""
echo -e "${GREEN}Controller bereit!${NC}"
echo -e "Wechsle in das Verzeichnis und starte ihn:"
echo -e "  ${YELLOW}cd $CONTROLLER_DIR && python3 controller/main.py${NC}"