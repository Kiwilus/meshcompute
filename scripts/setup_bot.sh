#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}MeshCompute Bot Builder${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Python3 wird benötigt.${NC}"
    exit 1
fi

REPO_URL="https://github.com/Kiwilus/meshcompute.git"
BOT_DIR="$(pwd)/meshcompute-bot"

if [ ! -d "$BOT_DIR" ]; then
    git clone "$REPO_URL" "$BOT_DIR"
fi
cd "$BOT_DIR"

pip3 install -r requirements.txt -q

# Konfiguration abfragen
read -p "Bot-ID (z.B. mein-bot-1): " BOT_ID
read -p "Bot-Secret: " BOT_SECRET
read -p "Server-URL (z.B. wss://mein-server.de:443/ws): " SERVER_URL

read -p "Für welche Plattform bauen? (exe/apk): " PLATFORM

# Client config.py erstellen
cat > client/config.py << EOF
BOT_ID = "$BOT_ID"
BOT_SECRET = "$BOT_SECRET"
SERVER_URL = "$SERVER_URL"
EOF

echo -e "${GREEN}Konfiguration geschrieben. Baue Bot...${NC}"

if [ "$PLATFORM" = "exe" ]; then
    # PyInstaller muss installiert sein
    if ! pip3 show pyinstaller &>/dev/null; then
        pip3 install pyinstaller -q
    fi
    python3 -m PyInstaller --onefile --name "meshbot_$BOT_ID" --add-data "client/config.py:." client/main.py
    echo -e "${GREEN}EXE erstellt: dist/meshbot_${BOT_ID}.exe${NC}"

elif [ "$PLATFORM" = "apk" ]; then
    if ! command -v buildozer &>/dev/null; then
        echo -e "${RED}Buildozer nicht gefunden. Installiere es zuerst: pip install buildozer${NC}"
        exit 1
    fi
    # Einfaches APK-Build-Verzeichnis
    APK_DIR="$BOT_DIR/apk_build"
    rm -rf "$APK_DIR"
    mkdir -p "$APK_DIR"
    cp client/main.py "$APK_DIR/"
    cp client/config.py "$APK_DIR/"
    cat > "$APK_DIR/buildozer.spec" << SPECEOF
[app]
title = MeshBot $BOT_ID
package.name = meshbot_$BOT_ID
package.domain = org.meshcompute
source.dir = .
source.include_exts = py
version = 1.0
requirements = python3,websockets,psutil
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 31
android.minapi = 21
android.ndk = 23b
android.sdk = 31
p4a.branch = master
SPECEOF
    cd "$APK_DIR"
    buildozer -v android debug
    APK_FILE=$(find . -name "*.apk" | head -1)
    if [ -f "$APK_FILE" ]; then
        cp "$APK_FILE" "$BOT_DIR/meshbot_${BOT_ID}.apk"
        echo -e "${GREEN}APK erstellt: $BOT_DIR/meshbot_${BOT_ID}.apk${NC}"
    else
        echo -e "${RED}APK-Bau fehlgeschlagen.${NC}"
        exit 1
    fi
else
    echo -e "${RED}Ungültige Plattform. Bitte 'exe' oder 'apk' wählen.${NC}"
    exit 1
fi