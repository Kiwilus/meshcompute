import asyncio
import websockets
import json
import time
import redis.asyncio as redis
import logging
from common.config import AUTH_TOKEN, REDIS_URL

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MeshServer:
    def __init__(self):
        self.clients = {}          # ws -> bot_info
        self.controllers = set()
        self.redis = None

    async def get_redis(self):
        if not self.redis:
            self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self.redis

    async def register_client(self, ws, bot_id: str):
        self.clients[ws] = {
            "bot_id": bot_id or f"bot_{int(time.time())}",
            "hostname": "unknown",
            "last_seen": time.time(),
            "status": "online"
        }
        logging.info(f"✅ Client registriert: {bot_id}")

    async def remove_client(self, ws):
        if ws in self.clients:
            bot_id = self.clients[ws]["bot_id"]
            del self.clients[ws]
            logging.info(f"❌ Client disconnected: {bot_id}")

    async def broadcast_task(self, task: dict, target="all"):
        r = await self.get_redis()
        count = 0
        for ws, info in list(self.clients.items()):
            if target == "all" or info["bot_id"] == target:
                try:
                    await r.rpush("mesh:tasks", json.dumps(task))
                    count += 1
                except Exception as e:
                    logging.error(f"Failed to queue task to {info['bot_id']}: {e}")
        return count

    async def handler(self, ws):
        """Einheitlicher Handler für alle Verbindungen"""
        try:
            # Erste Nachricht (Auth + Type)
            init_msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
            data = json.loads(init_msg)

            if data.get("type") == "controller" and data.get("auth_token") == AUTH_TOKEN:
                logging.info("Controller verbunden")
                self.controllers.add(ws)
                await self.handle_controller(ws)

            elif data.get("type") == "client":
                bot_id = data.get("bot_id")
                await self.register_client(ws, bot_id)
                await self.handle_client(ws)

            else:
                await ws.close(reason="Invalid connection type")

        except asyncio.TimeoutError:
            logging.warning("Timeout beim Verbindungsaufbau")
        except Exception as e:
            logging.error(f"Handler Error: {e}")
        finally:
            if ws in self.clients:
                await self.remove_client(ws)
            if ws in self.controllers:
                self.controllers.discard(ws)

    async def handle_client(self, ws):
        """Persistente Client Verbindung mit Heartbeat"""
        try:
            while True:
                msg = await ws.recv()
                data = json.loads(msg)

                if data["type"] == "heartbeat":
                    if ws in self.clients:
                        self.clients[ws]["last_seen"] = time.time()
        except Exception:
            pass  # Verbindung wird in finally geschlossen

    async def handle_controller(self, ws):
        """Persistente Controller Verbindung"""
        try:
            while True:
                msg = await ws.recv()
                data = json.loads(msg)

                if data.get("type") == "command":
                    task_id = data.get("task_id", f"task_{int(time.time())}")
                    command = {
                        "task_id": task_id,
                        "action": data["action"],
                        "target": data.get("target", "all"),
                        "payload": data.get("payload")
                    }

                    if data["action"] == "list":
                        bots = [{
                            "bot_id": info["bot_id"],
                            "hostname": info.get("hostname", "unknown"),
                            "status": info["status"],
                            "last_seen_sec": int(time.time() - info["last_seen"])
                        } for info in self.clients.values()]

                        await ws.send(json.dumps({
                            "type": "result",
                            "data": {"bots": bots, "count": len(bots)}
                        }))
                    else:
                        # Task an Redis Queue
                        sent = await self.broadcast_task(command, data.get("target", "all"))
                        await ws.send(json.dumps({
                            "type": "info",
                            "message": f"Task {task_id} an {sent} Client(s) queued."
                        }))

                elif data.get("type") == "get_result":
                    r = await self.get_redis()
                    result_json = await r.lpop(f"mesh:results:{data['task_id']}")
                    if result_json:
                        await ws.send(result_json)
                    else:
                        await ws.send(json.dumps({"type": "info", "message": "Result not ready yet"}))

        except Exception as e:
            logging.error(f"Controller connection error: {e}")

    async def main(self):
        print("🚀 MeshCompute Server (Redis + WebSocket) gestartet")
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            await asyncio.Future()  # läuft ewig


if __name__ == "__main__":
    server = MeshServer()
    asyncio.run(server.main())