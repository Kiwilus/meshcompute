import asyncio
import websockets
import json
import time
import logging
import redis.asyncio as redis
from common.config import AUTH_TOKEN, REDIS_URL

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

r = None

async def handler(websocket):
    try:
        raw = await websocket.recv()
        data = json.loads(raw)

        if data.get("auth_token") != AUTH_TOKEN:
            await websocket.send(json.dumps({"type": "error", "message": "Auth failed"}))
            return

        if data.get("type") == "controller":
            logger.info("Controller verbunden")
            async for msg_raw in websocket:
                msg = json.loads(msg_raw)
                if msg.get("type") == "command":
                    action = msg.get("action")
                    if action == "list":
                        bot_ids = await r.smembers("active_bots")
                        bot_list = []
                        for bid in bot_ids:
                            info_raw = await r.get(f"bot:{bid}:info")
                            last = await r.get(f"bot:{bid}:heartbeat")
                            if info_raw:
                                info = json.loads(info_raw)
                                bot_list.append({
                                    "bot_id": bid,
                                    "hostname": info.get("hostname", "?"),
                                    "last_seen_sec": int(time.time() - float(last or 0)),
                                    "status": "online" if (time.time() - float(last or 0)) < 60 else "offline"
                                })
                        await websocket.send(json.dumps({
                            "type": "result",
                            "data": {"bots": bot_list, "count": len(bot_list)}
                        }))
                    else:
                        task_id = msg.get("task_id", str(int(time.time()*1000)))
                        await r.rpush("mesh:tasks", json.dumps({
                            "task_id": task_id,
                            "action": action,
                            "target": msg.get("target", "all"),
                            "payload": msg.get("payload")
                        }))
                        await websocket.send(json.dumps({
                            "type": "info",
                            "message": f"Task {task_id} queued"
                        }))
                elif msg.get("type") == "get_result":
                    task_id = msg.get("task_id")
                    result = await r.blpop(f"mesh:results:{task_id}", timeout=30)
                    if result:
                        _, payload = result
                        await websocket.send(payload)
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Timeout"}))
        else:
            await websocket.send(json.dumps({"type": "error", "message": "Nur Controller erlaubt"}))
    except websockets.exceptions.ConnectionClosed:
        logger.info("Controller getrennt")
    except Exception as e:
        logger.error(f"Fehler: {e}")

async def cleanup():
    while True:
        bot_ids = await r.smembers("active_bots")
        for bid in bot_ids:
            last = await r.get(f"bot:{bid}:heartbeat")
            if not last or time.time() - float(last) > 120:
                await r.srem("active_bots", bid)
                await r.delete(f"bot:{bid}:info", f"bot:{bid}:heartbeat")
        await asyncio.sleep(30)

async def main():
    global r
    r = redis.from_url(REDIS_URL, decode_responses=True)
    asyncio.create_task(cleanup())
    async with websockets.serve(handler, "0.0.0.0", 8765):
        logger.info("MeshCompute Server läuft auf ws://0.0.0.0:8765")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
