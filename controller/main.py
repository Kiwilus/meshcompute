import asyncio
import websockets
import json
import logging
from colorama import init, Fore, Style
from dotenv import load_dotenv
from common.config import SERVER_URL, AUTH_TOKEN

load_dotenv()
init(autoreset=True)

logging.basicConfig(level=logging.INFO)

INTRO = f"""{Fore.CYAN}
=====================================
      MeshCompute Controller
=====================================
Befehle: list | exec <bot|all> <cmd> | sysinfo <bot|all>
         python <bot|all> <code> | ps <bot|all> | ping <bot|all> | exit
====================================={Style.RESET_ALL}"""
PROMPT = f"\n{Fore.GREEN}meshctrl > {Style.RESET_ALL}"

class MeshController:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.task_counter = 0

    def next_task_id(self):
        self.task_counter += 1
        return f"ctrl_{self.task_counter}"

    async def connect(self):
        try:
            self.ws = await websockets.connect(SERVER_URL, ping_interval=20)
            await self.ws.send(json.dumps({
                "type": "controller",
                "auth_token": AUTH_TOKEN
            }))
            self.connected = True
            print(f"{Fore.GREEN}[+] Mit Relay-Server verbunden{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[-] Verbindung fehlgeschlagen: {e}{Style.RESET_ALL}")
            self.connected = False

    async def send_command(self, command: dict):
        if not self.connected or not self.ws:
            print(f"{Fore.RED}Nicht verbunden.{Style.RESET_ALL}")
            return

        try:
            await self.ws.send(json.dumps(command))
            response_raw = await asyncio.wait_for(self.ws.recv(), timeout=30)
            response = json.loads(response_raw)
            self._print_result(response)
        except asyncio.TimeoutError:
            print(f"{Fore.RED}Timeout – keine Antwort.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Fehler: {e}{Style.RESET_ALL}")
            self.connected = False

    def _print_result(self, data: dict):
        if data.get("type") == "error":
            print(f"{Fore.RED}Fehler: {data.get('message')}{Style.RESET_ALL}")
            return

        if "bots" in data.get("data", {}):
            bots = data["data"]["bots"]
            print(f"\n{Fore.CYAN}=== Verbundene Bots ({len(bots)}) ==={Style.RESET_ALL}")
            for bot in bots:
                color = Fore.GREEN if bot.get("status") == "online" else Fore.RED
                print(f"  {color}{bot['bot_id']}{Style.RESET_ALL} | {bot.get('hostname', 'n/a')}")
            return

        bot_id = data.get("bot_id", "Unknown")
        print(f"\n{Fore.YELLOW}=== Ausgabe von {bot_id} ==={Style.RESET_ALL}")

        if data.get("info"):
            for k, v in data["info"].items():
                if k != "bot_id":
                    print(f"  {k:12}: {v}")
        elif data.get("processes"):
            for p in data["processes"][:20]:
                print(f"  {p['pid']:6} {p['name'][:40]:40} CPU: {p.get('cpu',0):.1f}%")
        elif data.get("output") is not None:
            print(data["output"].strip() or "(keine Ausgabe)")
            if data.get("error"):
                print(f"{Fore.RED}stderr: {data['error']}{Style.RESET_ALL}")
        elif data.get("success") is not None:
            status = Fore.GREEN if data["success"] else Fore.RED
            print(f"{status}{data.get('message', 'OK')}{Style.RESET_ALL}")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))

    async def handle_command(self, line: str):
        line = line.strip()
        if not line:
            return
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "list":
            await self.send_command({"type": "command", "action": "list", "task_id": self.next_task_id()})
        elif cmd == "exec":
            sub = arg.split(None, 1)
            if len(sub) < 2:
                print("Verwendung: exec <bot_id|all> <befehl>")
                return
            target, payload = sub
            await self.send_command({"type": "command", "action": "exec", "target": target, "payload": payload, "task_id": self.next_task_id()})
        elif cmd in ("sysinfo", "ps", "ping"):
            target = arg.strip() or "all"
            await self.send_command({"type": "command", "action": cmd, "target": target, "task_id": self.next_task_id()})
        elif cmd == "python":
            sub = arg.split(None, 1)
            if len(sub) < 2:
                print("Verwendung: python <bot_id|all> <code>")
                return
            target, payload = sub
            await self.send_command({"type": "command", "action": "python", "target": target, "payload": payload, "task_id": self.next_task_id()})
        elif cmd in ("exit", "quit"):
            print(f"{Fore.YELLOW}Beende Controller...{Style.RESET_ALL}")
            if self.ws:
                await self.ws.close()
            raise SystemExit
        elif cmd in ("clear", "cls"):
            print("\033c", end="")
        elif cmd == "help":
            print("Verfügbare Befehle: list, exec, sysinfo, python, ps, ping, clear, exit")
        else:
            print(f"{Fore.RED}Unbekannter Befehl. Tippe 'help'.{Style.RESET_ALL}")

async def main():
    print(INTRO)
    ctrl = MeshController()
    await ctrl.connect()
    if not ctrl.connected:
        return

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(None, input, PROMPT)
            await ctrl.handle_command(user_input)
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            print(f"Fehler: {e}")

if __name__ == "__main__":
    asyncio.run(main())