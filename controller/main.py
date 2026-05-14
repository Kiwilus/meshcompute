import asyncio
import websockets
import json
import time
import logging
import redis.asyncio as redis
from colorama import init, Fore, Style
from dotenv import load_dotenv
from common.config import SERVER_URL, AUTH_TOKEN, REDIS_URL
import os
import sys
import tty
import termios

load_dotenv()
init(autoreset=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROMPT = f"\n{Fore.GREEN}meshctrl > {Style.RESET_ALL}"


class MeshController:
    def __init__(self):
        self.ws = None
        self.redis = None
        self.connected = False
        self.task_counter = 0

    async def get_redis(self):
        if not self.redis:
            self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self.redis

    def next_task_id(self) -> str:
        self.task_counter += 1
        return f"task_{int(time.time())}_{self.task_counter}"

    async def connect(self):
        """Verbindung mit Reconnect-Versuch"""
        while True:
            try:
                self.ws = await websockets.connect(SERVER_URL, ping_interval=20, ping_timeout=30)
                await self.ws.send(json.dumps({
                    "type": "controller",
                    "auth_token": AUTH_TOKEN
                }))
                self.connected = True
                print(f"{Fore.GREEN}[+] Erfolgreich mit dem Relay-Server verbunden{Style.RESET_ALL}")
                return True
            except Exception as e:
                print(f"{Fore.RED}[-] Verbindung fehlgeschlagen: {type(e).__name__}: {e}{Style.RESET_ALL}")
                logger.exception("Verbindungsfehler im Detail:")  # schreibt den Traceback ins Log

    async def wait_for_result(self, task_id: str, timeout: int = 40):
        """Stabiles Warten auf Ergebnis über Redis"""
        r = await self.get_redis()
        result_key = f"mesh:results:{task_id}"

        print(f"{Fore.CYAN}Warte auf Ergebnis (max {timeout}s)...{Style.RESET_ALL}")

        try:
            result = await asyncio.wait_for(
                r.blpop(result_key, timeout=timeout),
                timeout=timeout + 2
            )

            if result:
                _, result_raw = result
                data = json.loads(result_raw)
                self._print_result(data)
                await r.delete(result_key)
                return data

        except asyncio.TimeoutError:
            print(f"{Fore.RED}Timeout: Kein Ergebnis innerhalb von {timeout} Sekunden.{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"Fehler beim Result-Fetch: {e}")
            print(f"{Fore.RED}Fehler beim Abrufen des Ergebnisses.{Style.RESET_ALL}")

    async def send_command(self, action: str, target: str = "all", payload: str = None):
        if not self.connected or not self.ws:
            print(f"{Fore.RED}Nicht verbunden. Versuche neu zu verbinden...{Style.RESET_ALL}")
            await self.connect()
            return

        task_id = self.next_task_id()

        command = {
            "type": "command",
            "task_id": task_id,
            "action": action,
            "target": target,
            "payload": payload
        }

        try:
            await self.ws.send(json.dumps(command))

            response_raw = await asyncio.wait_for(self.ws.recv(), timeout=8)
            response = json.loads(response_raw)
            self._print_result(response)

            if action == "list":
                return

            await self.wait_for_result(task_id)

        except asyncio.TimeoutError:
            print(f"{Fore.RED}Timeout beim Senden/Empfangen.{Style.RESET_ALL}")
        except websockets.exceptions.ConnectionClosed:
            print(f"{Fore.RED}Verbindung zum Server verloren.{Style.RESET_ALL}")
            self.connected = False
        except Exception as e:
            logger.error(f"Fehler beim Senden: {e}")
            print(f"{Fore.RED}Fehler: {e}{Style.RESET_ALL}")

    def _print_result(self, data: dict):
        """Verbesserte Ausgabe"""
        if not data:
            return

        if data.get("type") == "info":
            print(f"{Fore.BLUE}{data.get('message')}{Style.RESET_ALL}")
            return

        if data.get("type") == "result" and "data" in data:
            bots = data["data"].get("bots")
            if bots is None:
                bots = []
            print(f"\n{Fore.CYAN}=== Verbundene Bots ({len(bots)}) ==={Style.RESET_ALL}")
            for bot in bots:
                color = Fore.GREEN if bot.get("status") == "online" else Fore.YELLOW
                print(f"  {color}{bot['bot_id']}{Style.RESET_ALL} | "
                      f"{bot.get('hostname', 'n/a')} | "
                      f"{bot.get('last_seen_sec', 0)}s ago")
            return

        bot_id = data.get("bot_id", "Unknown")
        print(f"\n{Fore.YELLOW}=== Ergebnis von {bot_id} ==={Style.RESET_ALL}")

        if data.get("info"):
            print(f"{Fore.CYAN}System Information:{Style.RESET_ALL}")
            for k, v in data["info"].items():
                if k != "bot_id":
                    print(f"  {k:15}: {v}")
        elif data.get("processes"):
            print(f"{Fore.CYAN}Top Prozesse:{Style.RESET_ALL}")
            for p in data["processes"][:15]:
                print(f"  {p['pid']:6} {p['name'][:30]:30} CPU: {p.get('cpu', 0):.1f}%")
        elif data.get("output") is not None or data.get("success") is not None:
            if data.get("success"):
                print(f"{Fore.GREEN}Erfolg{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}Fehlgeschlagen{Style.RESET_ALL}")

            if data.get("output"):
                print(data["output"].strip())
            if data.get("error"):
                print(f"{Fore.RED}Error: {data['error']}{Style.RESET_ALL}")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))

    # --- NEUE METHODE (korrekt eingerückt) ---
    async def shell_session(self, target_id: str):
        if not self.connected or not self.ws:
            print(f"{Fore.RED}Nicht verbunden.{Style.RESET_ALL}")
            return

        shell_req = {
            "type": "command",
            "action": "shell",
            "target": target_id
        }
        await self.ws.send(json.dumps(shell_req))

        try:
            response_raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
            response = json.loads(response_raw)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            print(f"{Fore.RED}Keine Antwort vom Server.{Style.RESET_ALL}")
            return

        if response.get("type") != "shell_started":
            print(f"{Fore.RED}Shell konnte nicht gestartet werden: {response.get('message', '')}{Style.RESET_ALL}")
            return

        shell_id = response["shell_id"]
        print(f"{Fore.GREEN}Verbunden mit Shell auf {target_id}. Exit mit Ctrl+D oder exit.{Style.RESET_ALL}")

        old_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())

        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()

        async def send_input():
            try:
                while not stop_event.is_set():
                    char = await loop.run_in_executor(None, sys.stdin.read, 1)
                    if not char:
                        break
                    try:
                        await self.ws.send(json.dumps({
                            "type": "shell_input",
                            "shell_id": shell_id,
                            "data": char
                        }))
                    except:
                        break
            finally:
                stop_event.set()  # falls send_input endet, auch receive beenden

        async def receive_output():
            try:
                while not stop_event.is_set():
                    try:
                        msg = await asyncio.wait_for(self.ws.recv(), timeout=0.3)
                        data = json.loads(msg)
                        if data.get("type") == "shell_output" and data.get("shell_id") == shell_id:
                            sys.stdout.write(data["data"])
                            sys.stdout.flush()
                        elif data.get("type") == "shell_exit" and data.get("shell_id") == shell_id:
                            break
                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        break
            finally:
                stop_event.set()

        try:
            await asyncio.gather(send_input(), receive_output())
        finally:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
            print(f"\n{Fore.YELLOW}[Shell-Sitzung beendet]{Style.RESET_ALL}")

    async def handle_command(self, line: str):
        line = line.strip()
        if not line:
            return

        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "list":
            await self.send_command("list")

        elif cmd == "exec" and len(parts) >= 3:
            target = parts[1]
            payload = parts[2]
            await self.send_command("exec", target, payload)

        elif cmd == "shell" and len(parts) >= 2:
            target = parts[1]
            await self.shell_session(target)

        elif cmd == "sysinfo":
            target = parts[1] if len(parts) > 1 else "all"
            await self.send_command("sysinfo", target)

        elif cmd == "python" and len(parts) >= 3:
            target = parts[1]
            payload = parts[2]
            await self.send_command("python", target, payload)

        elif cmd == "ps":
            target = parts[1] if len(parts) > 1 else "all"
            await self.send_command("ps", target)

        elif cmd == "ping":
            target = parts[1] if len(parts) > 1 else "all"
            await self.send_command("ping", target)

        elif cmd in ("exit", "quit"):
            print(f"{Fore.YELLOW}Controller wird beendet...{Style.RESET_ALL}")
            if self.ws:
                await self.ws.close()
            raise SystemExit

        elif cmd == "help":
            print("""\nVerfügbare Befehle:
  list                        → Alle Bots anzeigen
  exec  <bot|all> <befehl>    → Shell-Befehl
  sysinfo <bot|all>           → Systeminfo
  python <bot|all> <code>     → Python Code
  ps    <bot|all>             → Prozesse
  ping  <bot|all>             → Ping
  shell <bot>                 → Interaktive Shell
  help | exit
""")
        else:
            print(f"{Fore.RED}Unbekannter Befehl. Tippe 'help'{Style.RESET_ALL}")


async def main():
    controller = MeshController()
    await controller.connect()

    while True:
        try:
            cmd_input = await asyncio.get_event_loop().run_in_executor(None, input, PROMPT)
            await controller.handle_command(cmd_input)
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logger.error(f"Hauptloop Fehler: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    print(f"{Fore.MAGENTA}MeshCompute Controller v2.1 (stabilisiert){Style.RESET_ALL}")
    asyncio.run(main())