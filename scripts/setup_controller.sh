#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${GREEN}MeshCompute Controller Setup${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Python3 fehlt.${NC}"; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"                     # meshcompute/ Hauptverzeichnis

echo -e "${GREEN}Verwende bestehendes Repository: $REPO_DIR${NC}"

# Token und URL abfragen
read -p "AUTH_TOKEN: " AUTH_TOKEN
read -p "Server-URL (z.B. wss://mein-server.de:443/ws): " SERVER_URL

cd "$REPO_DIR"

# Abhängigkeiten installieren (falls nicht schon geschehen)
pip3 install -r requirements.txt -q 2>/dev/null

# .env anlegen
cat > .env << EOF
AUTH_TOKEN=$AUTH_TOKEN
SERVER_URL=$SERVER_URL
EOF

# SSL-Context in controller/main.py einbauen, falls nicht vorhanden
if ! grep -q "ssl.create_default_context" controller/main.py; then
    echo -e "${GREEN}Passe Controller für selbstsigniertes TLS an...${NC}"
    # Ersetze die Verbindungszeile durch eine SSL-tolerante Version
    python3 -c "
import re
path = 'controller/main.py'
with open(path, 'r') as f:
    content = f.read()
old = '''            self.ws = await websockets.connect(
                SERVER_URL, ping_interval=20, ping_timeout=40
            )'''
new = '''            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.ws = await websockets.connect(
                SERVER_URL,
                ssl=ssl_context,
                ping_interval=20,
                ping_timeout=40
            )'''
if old in content:
    content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)
    print('SSL-Context eingefügt.')
else:
    print('SSL-Context bereits vorhanden oder Zeile nicht gefunden.')
"
fi

echo ""
echo -e "${GREEN}Controller bereit!${NC}"
echo -e "Starte ihn direkt aus dem Hauptverzeichnis:"
echo -e "  ${YELLOW}cd $REPO_DIR && python3 controller/main.py${NC}"