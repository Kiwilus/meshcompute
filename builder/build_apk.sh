#!/bin/bash
# builder/build_apk.sh
set -e

if [ $# -ne 1 ]; then
    echo "Verwendung: $0 <bot_id>"
    exit 1
fi

BOT_ID=$1
BUILDER_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$BUILDER_DIR/bot_configs/config_${BOT_ID}.py"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Konfiguration für '$BOT_ID' nicht gefunden."
    exit 1
fi

# Buildozer-Projektverzeichnis vorbereiten
PROJECT_DIR="$BUILDER_DIR/apk_build_$BOT_ID"
rm -rf "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR"

# main.py des Bots kopieren
cp "$BUILDER_DIR/../client/main.py" "$PROJECT_DIR/"

# Konfiguration als config.py hineinkopieren
cp "$CONFIG_FILE" "$PROJECT_DIR/config.py"

# Buildozer.spec erzeugen (stark vereinfacht)
cat > "$PROJECT_DIR/buildozer.spec" <<EOF
[app]
title = MeshBot ${BOT_ID}
package.name = meshbot_${BOT_ID}
package.domain = org.meshcompute
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
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
EOF

cd "$PROJECT_DIR"
echo "[+] Buildozer wird ausgeführt..."
buildozer -v android debug

APK_PATH=$(find . -name "*.apk" | head -1)
if [ -f "$APK_PATH" ]; then
    cp "$APK_PATH" "$BUILDER_DIR/meshbot_${BOT_ID}.apk"
    echo "[✓] APK erstellt: $BUILDER_DIR/meshbot_${BOT_ID}.apk"
else
    echo "❌ APK-Bau fehlgeschlagen."
    exit 1
fi