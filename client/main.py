import asyncio
import json
import uuid
import platform
import psutil
import time
import logging
import shlex
import os
from dotenv import load_dotenv
import redis.asyncio as redis
from common.config import REDIS_URL, MAX_COMMAND_TIMEOUT

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

r = None

async def execute_task(task_data: dict):
    """Führt eine Task aus und pusht Ergebnis zurück."""
    task_id = task_data["task_id"]
    action = task_data.get("action")
    payload = task_data.get("payload")

    result = {"task_id": task_id, "success": True, "output": "", "error": None}

    try:
        if action == "exec":
            output = subprocess.check_output(payload, shell=True, timeout=30, text=True)
            result["output"] = output
        elif action == "python":
            # Sicherer Exec (besser später sandboxen)
            local = {}
            exec(payload, {"__builtins__": {}}, local)
            result["output"] = str(local.get('result', 'OK'))
        elif action == "sysinfo":
            result["info"] = {
                "cpu": psutil.cpu_percent(),
                "memory": psutil.virtual_memory().percent,
                "hostname": psutil.os.uname().nodename,
                "bot_id": ...  # aus bot_id.txt laden
            }
        # TODO: Neue Actions wie "upload", "download", "llm_chunk" hinzufügen
        else:
            result["success"] = False
            result["error"] = f"Unbekannte Action: {action}"
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)

    # Ergebnis in Redis speichern
    await r.rpush(f"mesh:results:{task_id}", json.dumps(result))
    await r.expire(f"mesh:results:{task_id}", 300)  # 5 Min TTL


async def task_consumer():
    """Holt Tasks aus Redis Queue"""
    global r
    r = redis.from_url(REDIS_URL, decode_responses=True)

    while True:
        try:
            task = await r.blpop("mesh:tasks", timeout=5)
            if task:
                _, task_json = task
                task_data = json.loads(task_json)
                asyncio.create_task(execute_task(task_data))
        except Exception as e:
            print(f"Task Consumer Error: {e}")
            await asyncio.sleep(1)


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

    await r.rpush(f"mesh:results:{task_id}", json.dumps(result))
    await r.expire(f"mesh:results:{task_id}", 120)

async def heartbeat_loop(r: redis.Redis):
    tick = 0
    while True:
        await r.sadd("active_bots", bot_id)
        await r.set(f"bot:{bot_id}:heartbeat", time.time())
        # FIX: Zähler statt Modulo-Zeit – Info alle 30s erneuern
        if tick % 3 == 0:
            info = await get_system_info()
            await r.set(f"bot:{bot_id}:info", json.dumps(info))
        tick += 1
        await asyncio.sleep(10)

async def main():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    logger.info(f"Bot {bot_id} gestartet, verbinde mit Redis...")

    # FIX: Info sofort beim Start schreiben, damit Controller den Bot sieht
    info = await get_system_info()
    await r.set(f"bot:{bot_id}:info", json.dumps(info))
    await r.sadd("active_bots", bot_id)
    logger.info(f"Bot {bot_id} erfolgreich in Redis registriert.")

    heartbeat_task = asyncio.create_task(heartbeat_loop(r))

    while True:
        try:
            logger.info("Warte auf Aufgaben...")
            # FIX: None-Check vor dem Unpack
            result = await r.blpop("mesh:tasks", timeout=10)
            if result is None:
                continue
            _, task_raw = result
            task = json.loads(task_raw)
            target = task.get("target", "all")
            if target == "all" or target == bot_id or target == bot_id.split('-')[0]:
                logger.info(f"Verarbeite Task {task['task_id']} (Action: {task['action']})")
                await process_task(task, r)
            else:
                # Aufgabe nicht für uns – zurück in Queue
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