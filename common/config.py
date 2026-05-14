import os
import sys
from dotenv import load_dotenv

load_dotenv()

AUTH_TOKEN = os.getenv("AUTH_TOKEN")
if not AUTH_TOKEN:
    print("❌ FATAL: AUTH_TOKEN not set.", file=sys.stderr)
    sys.exit(1)

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8080"))
SERVER_URL = os.getenv("SERVER_URL", f"ws://{SERVER_HOST}:{SERVER_PORT}/ws")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MAX_COMMAND_TIMEOUT = int(os.getenv("MAX_COMMAND_TIMEOUT", "60"))