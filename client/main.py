import asyncio
import json
import uuid
import platform
import psutil
import time
import logging
import subprocess
import shlex
import os
from dotenv import load_dotenv
import redis.asyncio as redis
from common.config import REDIS_URL, AUTH_TOKEN, MAX_COMMAND_TIMEOUT

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot_id = f"{str(uuid.uuid4())[:8]}-{platform.node()[:8]}"

async def get_system_info():
    return {
        "hostname": platform.node(),
        "os": platform.system() + " " + platform.release(),
        "python": platform.python_version(),
        "cpu": psutil.cpu_count(logical=False),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "username": os.getenv("USER") or os.getenv("USERNAME"),
        "cwd": os.getcwd(),
        "bot_id": bot_id,
        "pid": os.getpid()
    }

async def execute_command(cmd: str, timeout=MAX_COMMAND_TIMEOUT):
    try:
        args = shlex.split(cmd)
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
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
    """Verarbeitet eine einzelne Aufgabe und sendet das Ergebnis."""
    task_id = task["task_id"]
    action = task["action"]
    payload = task.get("payload")
    result = {
        "type": "result",
        "task_id": task_id,
        "bot_id": bot_id
    }

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
        processes = [{"pid": p.info['pid'], "name": p.info['name'], "cpu": p.info['cpu_percent']}
                     for p in psutil.process_iter(['pid', 'name', 'cpu_percent'])]
        result.update({"success": True, "processes": processes[:50]})
    elif action == "ping":
        result.update({"success": True, "message": "pong"})
    else:
        result.update({"success": False, "error": f"Unbekannte Aktion: {action}"})

    # Ergebnis in eigene Queue pro Task schreiben (damit der Server es gezielt abholen kann)
    await r.rpush(f"mesh:results:{task_id}", json.dumps(result))
    # Optional: Expire setzen, damit die Queue nicht ewig wächst
    await r.expire(f"mesh:results:{task_id}", 120)

async def heartbeat_loop(r: redis.Redis):
    """Hält den Bot im active_bots Set und aktualisiert Heartbeat."""
    while True:
        await r.sadd("active_bots", bot_id)
        await r.set(f"bot:{bot_id}:heartbeat", time.time())
        # Info nur alle 30 Sek. erneuern, um Redis nicht zu überlasten
        if int(time.time()) % 30 == 0:
            info = await get_system_info()
            await r.set(f"bot:{bot_id}:info", json.dumps(info))
        await asyncio.sleep(10)

async def main():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    # Einfache Authentifizierung über Redis-Passwort (muss in REDIS_URL konfiguriert sein)
    # Alternativ könnte man hier einen Token prüfen, aber Redis selbst bietet Auth.
    logger.info(f"Bot {bot_id} gestartet, verbinde mit Redis...")

    # Heartbeat-Task starten
    heartbeat_task = asyncio.create_task(heartbeat_loop(r))

    # Hauptschleife: Aufgaben aus Queue holen
    while True:
        try:
            # Blockierend auf Aufgabe warten
            _, task_raw = await r.blpop("mesh:tasks", timeout=10)
            if task_raw is None:
                continue
            task = json.loads(task_raw)
            # Prüfen, ob Aufgabe für diesen Bot bestimmt ist (target: all oder spezifische ID)
            target = task.get("target", "all")
            if target == "all" or target == bot_id or target == bot_id.split('-')[0]:
                await process_task(task, r)
            else:
                # Aufgabe nicht für uns – wieder in Queue legen (einfach hinten anstellen)
                await r.rpush("mesh:tasks", task_raw)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Fehler in Hauptschleife: {e}")
            await asyncio.sleep(5)

    heartbeat_task.cancel()

if __name__ == "__main__":
    print(f"MeshCompute Client gestartet → {bot_id}")
    asyncio.run(main())