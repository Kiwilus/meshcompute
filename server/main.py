import asyncio
import websockets
import json
import time
import logging
import redis.asyncio as redis
from colorama import init, Fore, Style
from common.config import SERVER_HOST, SERVER_PORT, AUTH_TOKEN, REDIS_URL

init(autoreset=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Redis-Client global (wird beim Start verbunden)
r = None

async def authenticate(data: dict) -> bool:
    return data.get("auth_token") == AUTH_TOKEN

async def handler(websocket):
    """Behandelt Controller-Verbindungen. Bots verbinden sich direkt mit Redis."""
    try:
        first_msg = await websocket.recv()
        data = json.loads(first_msg)

        if not await authenticate(data):
            await websocket.send(json.dumps({"type": "error", "message": "Authentication failed"}))
            return

        client_type = data.get("type")

        if client_type == "controller":
            logger.info(f"{Fore.MAGENTA}Controller connected{Style.RESET_ALL}")
            # Controller-Schleife
            async for message in websocket:
                msg = json.loads(message)
                if msg["type"] == "command":
                    action = msg.get("action")
                    if action == "list":
                        # Bots aus Redis holen (alle, die in den letzten 60 Sek. Heartbeat hatten)
                        bot_ids = await r.smembers("active_bots")
                        bot_list = []
                        for bot_id in bot_ids:
                            info_raw = await r.get(f"bot:{bot_id}:info")
                            if info_raw:
                                info = json.loads(info_raw)
                                last_seen = float(await r.get(f"bot:{bot_id}:heartbeat") or 0)
                                bot_list.append({
                                    "bot_id": bot_id,
                                    "hostname": info.get("hostname", "Unknown"),
                                    "last_seen_sec": int(time.time() - last_seen),
                                    "status": "online" if time.time() - last_seen < 60 else "offline"
                                })
                        await websocket.send(json.dumps({
                            "type": "result",
                            "data": {"bots": bot_list, "count": len(bot_list)}
                        }))
                    else:
                        # Aufgabe in tasks-Queue legen
                        task_id = msg.get("task_id", str(int(time.time()*1000)))
                        task_data = {
                            "task_id": task_id,
                            "action": action,
                            "target": msg.get("target", "all"),
                            "payload": msg.get("payload")
                        }
                        await r.rpush("mesh:tasks", json.dumps(task_data))
                        # Nicht warten, Ergebnis kommt asynchron
                        # (Controller muss später Ergebnis abfragen – oder wir nutzen Pub/Sub)
                        await websocket.send(json.dumps({
                            "type": "info",
                            "message": f"Task {task_id} queued."
                        }))
                elif msg["type"] == "get_result":
                    task_id = msg.get("task_id")
                    # Blockierend auf Ergebnis warten (30 s Timeout)
                    result = await r.blpop(f"mesh:results:{task_id}", timeout=30)
                    if result:
                        _, payload = result
                        await websocket.send(payload.decode())
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": f"Timeout für Task {task_id}"
                        }))

        else:
            await websocket.send(json.dumps({"type": "error", "message": "Unbekannter Client-Typ"}))
    except websockets.exceptions.ConnectionClosed:
        logger.info("Controller disconnected")
    except Exception as e:
        logger.error(f"Error: {e}")

async def cleanup_bots():
    """Entfernt inaktive Bots regelmäßig aus dem Set."""
    while True:
        bot_ids = await r.smembers("active_bots")
        for bot_id in bot_ids:
            last = await r.get(f"bot:{bot_id}:heartbeat")
            if not last or time.time() - float(last) > 60:
                await r.srem("active_bots", bot_id)
                await r.delete(f"bot:{bot_id}:info")
                await r.delete(f"bot:{bot_id}:heartbeat")
        await asyncio.sleep(30)

async def main():
    global r
    r = redis.from_url(REDIS_URL, decode_responses=True)
    # Starte Cleanup-Task
    asyncio.create_task(cleanup_bots())

    async with websockets.serve(handler, SERVER_HOST, SERVER_PORT):
        logger.info(f"{Fore.GREEN}MeshCompute Server running on ws://{SERVER_HOST}:{SERVER_PORT}{Style.RESET_ALL}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())