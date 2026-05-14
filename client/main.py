import asyncio
import pty
import select
import json
import uuid
import platform
import psutil
import time
import logging
import shlex
import os
import sys
import socket
import traceback
import subprocess
from dotenv import load_dotenv
import redis.asyncio as redis
import websockets
from common.config import REDIS_URL, MAX_COMMAND_TIMEOUT, SERVER_URL

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_ID = os.getenv("BOT_ID", f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}")

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
            processes = [{"pid": p.info['pid'], "name": p.info['name'], "cpu": p.info['cpu_percent']}
                         for p in psutil.process_iter(['pid', 'name', 'cpu_percent'])]
            result.update({"success": True, "processes": processes[:50]})
        elif action == "ping":
            result.update({"success": True, "message": "pong"})
        else:
            result.update({"success": False, "error": f"Unbekannte Aktion: {action}"})
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)

    # Ergebnis in Redis ablegen
    result_key = f"mesh:results:{task_id}"
    await r.rpush(result_key, json.dumps(result))
    await r.expire(result_key, 300)

async def handle_shell(shell_id, ws):
    """Startet eine interaktive Shell und leitet I/O um."""
    master_fd, slave_fd = pty.openpty()
    pid = os.fork()
    if pid == 0:
        os.close(master_fd)
        os.setsid()
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        os.execvp("/bin/bash", ["/bin/bash"])
    else:
        os.close(slave_fd)
        loop = asyncio.get_event_loop()

        async def forward_to_server():
            while True:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if r:
                    data = os.read(master_fd, 1024)
                    if not data:
                        break
                    try:
                        await ws.send(json.dumps({
                            "type": "shell_output",
                            "shell_id": shell_id,
                            "data": data.decode('utf-8', errors='replace')
                        }))
                    except:
                        break
            os.waitpid(pid, 0)
            try:
                await ws.send(json.dumps({
                    "type": "shell_exit",
                    "shell_id": shell_id
                }))
            except:
                pass

        async def receive_from_server():
            while True:
                try:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("type") == "shell_input" and data.get("shell_id") == shell_id:
                        os.write(master_fd, data["data"].encode())
                except websockets.exceptions.ConnectionClosed:
                    break
                except:
                    break

        await asyncio.gather(forward_to_server(), receive_from_server())

async def main():
    r = await create_robust_redis()
    info = await get_system_info()
    await r.set(f"bot:{BOT_ID}:info", json.dumps(info), ex=120)
    await r.sadd("active_bots", BOT_ID)

    while True:
        try:
            async with websockets.connect(SERVER_URL, ping_interval=20, ping_timeout=30) as ws:
                # Registrierung als Client
                await ws.send(json.dumps({
                    "type": "client",
                    "bot_id": BOT_ID
                }))
                logger.info(f"Verbunden als {BOT_ID}")

                # Task-Verarbeitung über WebSocket
                async for raw_msg in ws:
                    msg = json.loads(raw_msg)
                    msg_type = msg.get("type", msg.get("action"))

                    if msg_type == "shell_request":
                        asyncio.create_task(handle_shell(msg["shell_id"], ws))
                    elif "task_id" in msg:  # normale Aufgabe (exec, sysinfo, ...)
                        asyncio.create_task(process_task(msg, r))
                    else:
                        logger.warning(f"Unbekannte Nachricht: {msg}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket-Verbindung verloren, reconnect in 3s...")
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Client-Fehler: {e}")
            await asyncio.sleep(3)

async def create_robust_redis():
    backoff = 1
    while True:
        try:
            r = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=60,
                socket_keepalive=True,
                health_check_interval=30,
                retry_on_timeout=True
            )
            await r.ping()
            logger.info("✅ Redis erfolgreich verbunden")
            return r
        except Exception as e:
            logger.error(f"Redis Verbindungsfehler: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

if __name__ == "__main__":
    print(f"MeshCompute Client gestartet → {BOT_ID}")
    asyncio.run(main())