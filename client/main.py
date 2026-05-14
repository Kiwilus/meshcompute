# client/main.py
import asyncio
import json
import uuid
import platform
import psutil
import logging
import shlex
import os
import socket
import base64
from pathlib import Path
from dotenv import load_dotenv
import websockets

# Importiere Konfiguration aus common
from common.config import SERVER_URL as DEFAULT_SERVER_URL, MAX_COMMAND_TIMEOUT

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ====================== KONFIGURATION ======================
def load_config():
    """Liest Bot-Konfiguration aus bot_config.json, Umgebungsvariablen oder Standardwerten."""
    # 1. bot_config.json (höchste Priorität)
    config_path = Path("bot_config.json")
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            return (
                data.get("bot_id") or data.get("BOT_ID"),
                data.get("bot_secret") or data.get("BOT_SECRET"),
                data.get("server_url") or data.get("SERVER_URL")
            )
        except Exception as e:
            logger.error(f"Konfigurationsdatei beschädigt: {e}")

    # 2. Umgebungsvariablen (teilweise befüllt möglich)
    bot_id = os.getenv("BOT_ID")
    bot_secret = os.getenv("BOT_SECRET")
    server_url = os.getenv("SERVER_URL")

    # Wenn nur BOT_SECRET gesetzt ist, ergänze die fehlenden Werte automatisch
    if bot_secret and not bot_id:
        # BOT_ID aus vorhandener Datei oder neu generieren
        id_file = Path("client/bot_id.txt")
        if id_file.exists():
            bot_id = id_file.read_text().strip()
        else:
            bot_id = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"
            id_file.parent.mkdir(parents=True, exist_ok=True)
            id_file.write_text(bot_id)

    if bot_secret and not server_url:
        server_url = DEFAULT_SERVER_URL  # aus common/config.py

    # Nur zurückgeben, wenn mindestens ID und URL vorhanden sind
    if bot_id and server_url:
        return bot_id, bot_secret, server_url

    return None, None, None

BOT_ID, BOT_SECRET, SERVER_URL = load_config()
if not BOT_ID or not SERVER_URL:
    print("❌ Keine gültige Konfiguration gefunden.")
    print("Erstelle eine 'bot_config.json' im gleichen Ordner wie diese EXE mit:")
    print('{"bot_id": "dein-bot", "bot_secret": "geheim", "server_url": "wss://server:443/ws"}')
    print("Alternativ setze die Umgebungsvariablen BOT_ID, BOT_SECRET und SERVER_URL.")
    import sys
    sys.exit(1)

# ====================== HILFSFUNKTIONEN ======================
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

# ====================== MAIN ======================
async def main():
    print(f"MeshCompute Client gestartet → {BOT_ID}")
    while True:
        try:
            # SSL-Kontext für selbstsignierte Zertifikate
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            async with websockets.connect(SERVER_URL, ssl=ssl_context, ping_interval=20, ping_timeout=40) as ws:
                await ws.send(json.dumps({
                    "type": "client",
                    "bot_id": BOT_ID,
                    "bot_secret": BOT_SECRET or ""
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
                                    processes = [{"pid": p.info['pid'], "name": p.info['name']}
                                                 for p in psutil.process_iter(['pid', 'name'])][:30]
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