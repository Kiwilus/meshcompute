#!/usr/bin/env python3
# builder/generate_secrets.py
import os, secrets, json, sys
from pathlib import Path

BUILDER_DIR = Path(__file__).resolve().parent
BOT_CONFIGS_DIR = BUILDER_DIR / "bot_configs"
OUTPUT_ENV = BUILDER_DIR.parent / ".env"

# Anzahl der Bots anpassen:
NUM_BOTS = 3

def gen_token(length=32):
    return secrets.token_hex(length)

def main():
    # Verzeichnisse vorbereiten
    BOT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    # Auth-Token für Controller
    auth_token = gen_token()
    print(f"[+] AUTH_TOKEN = {auth_token}")

    # Bot-Secrets
    bot_secrets = {}
    bot_names = []

    for i in range(1, NUM_BOTS + 1):
        bot_id = f"bot{i:02d}"
        secret = gen_token(16)
        bot_secrets[bot_id] = secret
        bot_names.append(bot_id)
        print(f"[+] Bot {bot_id}: BOT_SECRET = {secret}")

        # Bot‑Konfigurationsdatei schreiben
        config = f'BOT_ID = "{bot_id}"\nBOT_SECRET = "{secret}"\n'
        # Server-URL kann hier festgelegt werden (später ggf. als Parameter)
        config += 'SERVER_URL = "ws://localhost:8080/ws"\n'
        (BOT_CONFIGS_DIR / f"config_{bot_id}.py").write_text(config)

    # .env für Server und Controller
    env_content = f"""# MeshCompute Umgebungsvariablen
AUTH_TOKEN={auth_token}
BOT_SECRETS='{json.dumps(bot_secrets)}'
REDIS_URL=redis://redis:6379
REDIS_PASSWORD=redis_geheim
SERVER_PORT=8080
# TLS (optional)
# TLS_CERT=/pfad/cert.pem
# TLS_KEY=/pfad/key.pem
"""
    OUTPUT_ENV.write_text(env_content)
    print(f"\n[✓] Secrets gespeichert in {OUTPUT_ENV}")
    print(f"[✓] Bot-Konfigurationen in {BOT_CONFIGS_DIR}")

if __name__ == "__main__":
    main()