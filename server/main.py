import asyncio
import websockets
import json
import time
import logging
from colorama import init, Fore, Style
from common.config import SERVER_HOST, SERVER_PORT, AUTH_TOKEN

init(autoreset=True)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bots = {}
controllers = []

async def authenticate(data: dict) -> bool:
    return data.get("auth_token") == AUTH_TOKEN

async def broadcast_to_bots(msg: dict):
    target = msg.get("target", "all")
    targets = list(bots.keys()) if target == "all" else [target] if target in bots else []

    for bot_id in targets:
        try:
            await bots[bot_id]["ws"].send(json.dumps({
                "type": "command",
                "task_id": msg.get("task_id"),
                "data": {
                    "type": msg.get("action"),
                    "payload": msg.get("payload")
                }
            }))
        except Exception:
            pass
    return len(targets)

async def handler(websocket):
    try:
        first_msg = await websocket.recv()
        data = json.loads(first_msg)

        if not await authenticate(data):
            await websocket.send(json.dumps({"type": "error", "message": "Authentication failed"}))
            return

        client_type = data.get("type")

        if client_type == "register":
            bot_id = data["bot_id"]
            bots[bot_id] = {
                "ws": websocket,
                "hostname": data["info"].get("hostname", "Unknown"),
                "last_seen": time.time(),
                "info": data["info"]
            }
            logger.info(f"{Fore.GREEN}Bot connected: {bot_id} | {bots[bot_id]['hostname']}{Style.RESET_ALL}")

            async for message in websocket:
                msg = json.loads(message)
                if msg["type"] == "result" or msg["type"] == "heartbeat":
                    if msg["type"] == "heartbeat":
                        if bot_id in bots:
                            bots[bot_id]["last_seen"] = time.time()
                        continue

                    for ctrl in controllers[:]:
                        try:
                            await ctrl.send(json.dumps(msg))
                        except:
                            controllers.remove(ctrl) if ctrl in controllers else None

        elif client_type == "controller":
            controllers.append(websocket)
            logger.info(f"{Fore.MAGENTA}Controller connected{Style.RESET_ALL}")

            async for message in websocket:
                msg = json.loads(message)
                if msg["type"] == "command":
                    if msg.get("action") == "list":
                        bot_list = [
                            {
                                "bot_id": bid,
                                "hostname": info["hostname"],
                                "last_seen_sec": int(time.time() - info["last_seen"]),
                                "status": "online" if time.time() - info["last_seen"] < 60 else "offline"
                            }
                            for bid, info in bots.items()
                        ]
                        await websocket.send(json.dumps({
                            "type": "result",
                            "data": {"bots": bot_list, "count": len(bots)}
                        }))
                    else:
                        await broadcast_to_bots(msg)

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        # Cleanup
        if websocket in controllers:
            controllers.remove(websocket)
        for bid, info in list(bots.items()):
            if info["ws"] == websocket:
                logger.info(f"{Fore.RED}Bot disconnected: {bid}{Style.RESET_ALL}")
                del bots[bid]

async def main():
    async with websockets.serve(handler, SERVER_HOST, SERVER_PORT):
        logger.info(f"{Fore.GREEN}MeshCompute Server running on ws://{SERVER_HOST}:{SERVER_PORT}{Style.RESET_ALL}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())