#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${GREEN}MeshCompute Bot Builder (Linux)${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Python3 fehlt.${NC}"; exit 1
fi

read -p "Server-URL (z.B. wss://mein-server.de:443/ws): " SERVER_URL
read -p "Registration Token: " REG_TOKEN

echo ""
echo "Wähle die Zielplattform:"
echo "  linux   – Linux Binary"
echo "  apk     – Android APK (Buildozer nötig)"
echo "  windows – ❌ Windows-EXE kann hier nicht gebaut werden (benutze setup_bot_windows.bat)"
echo ""
read -p "Plattform (linux/apk): " PLATFORM

if [ "$PLATFORM" = "windows" ]; then
    echo -e "${RED}Windows-EXE kann nur unter Windows gebaut werden.${NC}"
    exit 1
elif [ "$PLATFORM" != "linux" ] && [ "$PLATFORM" != "apk" ]; then
    echo -e "${RED}Ungültige Auswahl.${NC}"; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CLIENT_FILE="$REPO_DIR/client/main.py"

if [ ! -f "$CLIENT_FILE" ]; then
    echo -e "${YELLOW}Repository nicht gefunden, klone einmalig...${NC}"
    git clone https://github.com/Kiwilus/meshcompute.git "$REPO_DIR"
fi

cd "$REPO_DIR"
pip3 install -r requirements.txt -q 2>/dev/null

BUILD_DIR="$HOME/meshcompute-build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp "$CLIENT_FILE" "$BUILD_DIR/main.py"

# build_config.py erzeugen (wird von PyInstaller in die EXE eingebettet)
cat > "$BUILD_DIR/build_config.py" << EOF
SERVER_URL = "$SERVER_URL"
REGISTRATION_TOKEN = "$REG_TOKEN"
EOF

cd "$BUILD_DIR"

if [ "$PLATFORM" = "linux" ]; then
    if ! python3 -c "import PyInstaller" &>/dev/null; then
        pip3 install pyinstaller -q
    fi
    echo -e "${GREEN}Baue Linux-Binary...${NC}"
    python3 -m PyInstaller --onefile --name "meshbot" \
        --add-data "build_config.py:." main.py
    echo -e "${GREEN}Linux-Binary: $BUILD_DIR/dist/meshbot${NC}"

elif [ "$PLATFORM" = "apk" ]; then
    if ! command -v buildozer &>/dev/null; then
        echo -e "${RED}Buildozer fehlt.${NC}"; exit 1
    fi
    echo -e "${GREEN}Baue Android APK...${NC}"
    cat > buildozer.spec << SPECEOF
[app]
title = MeshBot
package.name = meshbot
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
    buildozer -v android debug
    APK_FILE=$(find . -name "*.apk" | head -1)
    if [ -f "$APK_FILE" ]; then
        cp "$APK_FILE" "$BUILD_DIR/meshbot.apk"
        echo -e "${GREEN}APK erstellt: $BUILD_DIR/meshbot.apk${NC}"
    else
        echo -e "${RED}APK-Bau fehlgeschlagen.${NC}"; exit 1
    fi
fi