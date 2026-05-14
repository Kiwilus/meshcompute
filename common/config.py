import os
import sys
from dotenv import load_dotenv

load_dotenv()

AUTH_TOKEN = os.getenv("AUTH_TOKEN")
if not AUTH_TOKEN:
    print("❌ FATAL: AUTH_TOKEN nicht gesetzt.", file=sys.stderr)
    sys.exit(1)

SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = os.getenv("SERVER_PORT", "8080")

# WebSocket-URL: wichtig ist der Pfad /ws, den der Go-Server erwartet!
SERVER_URL = os.getenv("SERVER_URL", f"ws://{SERVER_HOST}:{SERVER_PORT}/ws")

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")

MAX_COMMAND_TIMEOUT = int(os.getenv("MAX_COMMAND_TIMEOUT", "30"))