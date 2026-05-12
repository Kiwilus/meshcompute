import asyncio
import websockets
import json
import uuid
import platform
import psutil
import os
from config import SERVER_URL, RECONNECT_DELAY

BOT_ID = str(uuid.uuid4())[:8]  # kurze ID für Übersichtlichkeit

async def get_system_info():
    return {
        "hostname": platform.node(),
        "os": platform.system(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "python": platform.python_version()
    }

async def client():
    while True:
        try:
            async with websockets.connect(SERVER_URL) as ws:
                print(f"[{BOT_ID}] Verbunden mit Server")

                # Registrieren
                await ws.send(json.dumps({
                    "type": "register",
                    "bot_id": BOT_ID,
                    "info": await get_system_info()
                }))

                async for message in ws:
                    data = json.loads(message)

                    if data["type"] == "command":
                        task_id = data.get("task_id")
                        cmd_type = data["data"].get("type")

                        if cmd_type == "system_info":
                            result = await get_system_info()
                        elif cmd_type == "ping":
                            result = "pong"
                        else:
                            result = "Unbekannter Befehl"

                        await ws.send(json.dumps({
                            "type": "result",
                            "bot_id": BOT_ID,
                            "task_id": task_id,
                            "data": result
                        }))

        except Exception as e:
            print(f"[{BOT_ID}] Verbindung verloren: {e}")
            await asyncio.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    print(f"Client gestartet - ID: {BOT_ID}")
    asyncio.run(client())