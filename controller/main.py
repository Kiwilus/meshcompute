import asyncio
import websockets
import json
import time
import logging
from colorama import init, Fore, Style
from dotenv import load_dotenv
from common.config import SERVER_URL, AUTH_TOKEN

load_dotenv()
init(autoreset=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

INTRO = f"""{Fore.CYAN}
=====================================
      MeshCompute Controller v2 (Redis)
=====================================
Befehle: list | exec <bot|all> <cmd> | sysinfo <bot|all>
         python <bot|all> <code> | ps <bot|all> | ping <bot|all>
         queue | upload | help | exit
====================================={Style.RESET_ALL}
"""
PROMPT = f"\n{Fore.GREEN}meshctrl > {Style.RESET_ALL}"


class MeshController:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.task_counter = 0

    def next_task_id(self) -> str:
        self.task_counter += 1
        return f"ctrl_{int(time.time())}_{self.task_counter}"

    async def connect(self):
        try:
            self.ws = await websockets.connect(SERVER_URL)
            await self.ws.send(json.dumps({
                "type": "controller",
                "auth_token": AUTH_TOKEN
            }))
            self.connected = True
            print(f"{Fore.GREEN}[+] Erfolgreich mit dem Server verbunden{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[-] Verbindung fehlgeschlagen: {e}{Style.RESET_ALL}")
            self.connected = False

    async def send_command(self, command: dict, wait_result: bool = True):
        """Sendet einen Befehl und verarbeitet die Antwort."""
        if not self.connected or not self.ws:
            print(f"{Fore.RED}Nicht verbunden.{Style.RESET_ALL}")
            return

        try:
            await self.ws.send(json.dumps(command))

            # Erste Antwort (meist "Task queued" oder direktes Ergebnis)
            response_raw = await asyncio.wait_for(self.ws.recv(), timeout=8)
            response = json.loads(response_raw)
            self._print_result(response)

            # Bei Tasks, die Ergebnisse liefern sollen, zusätzlich abfragen
            if wait_result and command.get("action") not in ["list"]:
                task_id = command.get("task_id")
                if task_id:
                    await asyncio.sleep(0.5)  # kurze Wartezeit
                    await self.ws.send(json.dumps({
                        "type": "get_result",
                        "task_id": task_id
                    }))
                    result_raw = await asyncio.wait_for(self.ws.recv(), timeout=30)
                    result = json.loads(result_raw)
                    self._print_result(result)

        except asyncio.TimeoutError:
            print(f"{Fore.RED}Timeout – keine Antwort vom Server.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Fehler beim Senden: {e}{Style.RESET_ALL}")
            self.connected = False

    def _print_result(self, data: dict):
        """Gibt Ergebnisse schön formatiert aus."""
        msg_type = data.get("type")

        if msg_type == "error":
            print(f"{Fore.RED}Fehler: {data.get('message')}{Style.RESET_ALL}")
            return

        if msg_type == "info":
            print(f"{Fore.BLUE}{data.get('message')}{Style.RESET_ALL}")
            return

        # Bot-Liste
        if "bots" in data.get("data", {}):
            bots = data["data"]["bots"]
            print(f"\n{Fore.CYAN}=== Verbundene Bots ({data['data'].get('count', 0)}) ==={Style.RESET_ALL}")
            if not bots:
                print("  (keine Bots online)")
            for bot in bots:
                color = Fore.GREEN if bot.get("status") == "online" else Fore.RED
                print(f"  {color}{bot.get('bot_id')}{Style.RESET_ALL} | "
                      f"{bot.get('hostname')} | "
                      f"Zuletzt: {bot.get('last_seen_sec', 0)}s")
            return

        # Normale Task-Ergebnisse
        bot_id = data.get("bot_id", "Unknown")
        print(f"\n{Fore.YELLOW}=== Ausgabe von {bot_id} ==={Style.RESET_ALL}")

        if data.get("info"):
            print(f"{Fore.CYAN}System Information:{Style.RESET_ALL}")
            for k, v in data["info"].items():
                if k != "bot_id":
                    print(f"  {k:12}: {v}")
        elif data.get("processes"):
            print(f"{Fore.CYAN}Prozesse:{Style.RESET_ALL}")
            for p in data["processes"][:15]:
                print(f"  {p.get('pid'):6}  {str(p.get('name',''))[:35]:35}  CPU: {p.get('cpu',0):.1f}%")
        elif data.get("output") is not None:
            output = str(data.get("output", "")).strip()
            print(output if output else "(keine Ausgabe)")
            if data.get("error"):
                print(f"{Fore.RED}Fehler: {data['error']}{Style.RESET_ALL}")
        elif data.get("success") is not None:
            status = Fore.GREEN if data["success"] else Fore.RED
            print(f"{status}{data.get('message', 'OK' if data['success'] else 'Fehlgeschlagen')}{Style.RESET_ALL}")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))

    async def handle_command(self, line: str):
        line = line.strip()
        if not line:
            return

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        task_id = self.next_task_id()

        if cmd == "list":
            await self.send_command({
                "type": "command",
                "action": "list",
                "task_id": task_id
            }, wait_result=False)

        elif cmd == "exec":
            parts2 = arg.split(None, 1)
            if len(parts2) < 2:
                print("Verwendung: exec <bot|all> <befehl>")
                return
            target, cmd_text = parts2
            await self.send_command({
                "type": "command",
                "action": "exec",
                "target": target,
                "payload": cmd_text,
                "task_id": task_id
            })

        elif cmd == "sysinfo":
            target = arg.strip() or "all"
            await self.send_command({
                "type": "command",
                "action": "sysinfo",
                "target": target,
                "task_id": task_id
            })

        elif cmd == "python":
            parts2 = arg.split(None, 1)
            if len(parts2) < 2:
                print("Verwendung: python <bot|all> <code>")
                return
            target, code = parts2
            await self.send_command({
                "type": "command",
                "action": "python",
                "target": target,
                "payload": code,
                "task_id": task_id
            })

        elif cmd in ("ps", "ping"):
            target = arg.strip() or "all"
            await self.send_command({
                "type": "command",
                "action": cmd,
                "target": target,
                "task_id": task_id
            })

        elif cmd == "queue":
            await self.send_command({
                "type": "command",
                "action": "queue_status",
                "task_id": task_id
            })

        elif cmd == "upload":
            print(f"{Fore.YELLOW}Upload-Funktion noch nicht vollständig implementiert.{Style.RESET_ALL}")
            print("Beispiel: upload <bot_id|all> <local_file> <remote_path>")

        elif cmd in ("exit", "quit"):
            print(f"{Fore.YELLOW}Controller wird beendet...{Style.RESET_ALL}")
            if self.ws:
                await self.ws.close()
            raise SystemExit

        elif cmd in ("clear", "cls"):
            print("\033c", end="")

        elif cmd == "help":
            print(INTRO)
        else:
            print(f"{Fore.RED}Unbekannter Befehl: {cmd}. Tippe 'help' für Hilfe.{Style.RESET_ALL}")


async def main():
    print(INTRO)
    controller = MeshController()
    await controller.connect()

    if not controller.connected:
        return

    while True:
        try:
            cmd_input = await asyncio.get_event_loop().run_in_executor(None, input, PROMPT)
            await controller.handle_command(cmd_input)
        except (KeyboardInterrupt, SystemExit):
            print(f"\n{Fore.YELLOW}Beendet.{Style.RESET_ALL}")
            break
        except Exception as e:
            logging.error(f"Fehler in main loop: {e}")


if __name__ == "__main__":
    print(f"{Fore.MAGENTA}MeshCompute Controller wird gestartet...{Style.RESET_ALL}")
    asyncio.run(main())