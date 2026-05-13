import os

AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8765
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
MAX_COMMAND_TIMEOUT = 30
