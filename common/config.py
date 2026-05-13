import os
from dotenv import load_dotenv

load_dotenv()

AUTH_TOKEN = os.getenv("AUTH_TOKEN", "default_insecure_token_change_me")
SERVER_URL = os.getenv("SERVER_URL", "ws://localhost:8765")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8765))

# Security
MAX_COMMAND_TIMEOUT = 120  # Sekunden