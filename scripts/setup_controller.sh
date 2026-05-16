#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}MeshCompute Controller Setup${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Python3 fehlt.${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${GREEN}Verwende bestehendes Repository: $REPO_DIR${NC}"

# Eingaben validieren
read -r -p "AUTH_TOKEN: " AUTH_TOKEN
if [[ -z "$AUTH_TOKEN" ]]; then
    echo -e "${RED}Fehler: AUTH_TOKEN darf nicht leer sein.${NC}"
    exit 1
fi

read -r -p "Server-URL (z.B. wss://mein-server.de:443/ws): " SERVER_URL
if [[ -z "$SERVER_URL" ]]; then
    echo -e "${RED}Fehler: Server-URL darf nicht leer sein.${NC}"
    exit 1
fi

cd "$REPO_DIR"

# Abhängigkeiten installieren (mit sichtbaren Fehlern)
pip3 install -r requirements.txt || {
    echo -e "${RED}Fehler: pip3 install fehlgeschlagen.${NC}"
    exit 1
}

# .env anlegen
cat > .env << EOF
AUTH_TOKEN=$AUTH_TOKEN
SERVER_URL=$SERVER_URL
EOF

# SSL-Context in controller/main.py einbauen
MAIN_PY="controller/main.py"
if [ ! -f "$MAIN_PY" ]; then
    echo -e "${RED}Fehler: $MAIN_PY nicht gefunden.${NC}"
    exit 1
fi

# Backup erstellen
cp "$MAIN_PY" "${MAIN_PY}.bak"

if grep -q "ssl.create_default_context" "$MAIN_PY"; then
    echo -e "${GREEN}SSL-Context bereits vorhanden.${NC}"
else
    echo -e "${GREEN}Passe Controller für selbstsigniertes TLS an...${NC}"

    # Python-Code als separate Datei, um Quoting-Probleme zu vermeiden
    python3 << 'PYEOF'
import re

path = "controller/main.py"
with open(path, "r") as f:
    content = f.read()

# Flexiblere Suche (ignoriert Whitespace-Unterschiede)
old_pattern = r'self\.ws\s*=\s*await\s+websockets\.connect\s*\(\s*SERVER_URL\s*,\s*ping_interval\s*=\s*20\s*,\s*ping_timeout\s*=\s*40\s*\)'
new_code = """import ssl
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
self.ws = await websockets.connect(
    SERVER_URL,
    ssl=ssl_context,
    ping_interval=20,
    ping_timeout=40
)"""

if re.search(old_pattern, content):
    content = re.sub(old_pattern, new_code, content)
    with open(path, "w") as f:
        f.write(content)
    print("SSL-Context eingefügt.")
else:
    print("Kein passendes Muster gefunden – bitte manuell anpassen.")
    print("Gesuchtes Muster: ", old_pattern)
PYEOF
fi

echo ""
echo -e "${GREEN}Controller bereit!${NC}"
echo -e "Starte ihn direkt aus dem Hauptverzeichnis:"
echo -e " ${YELLOW}cd $REPO_DIR && python3 controller/main.py${NC}"