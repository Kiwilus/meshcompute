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
                    action = data["action"]
                    task_id = data.get("task_id", f"task_{int(time.time())}")

                    if action == "list":
                        # NEU: Aus Redis lesen statt nur self.clients
                        r = await self.get_redis()
                        bot_ids = await r.smembers("active_bots")

                        bots = []
                        for bid in bot_ids:
                            info_raw = await r.get(f"bot:{bid}:info")
                            last_heartbeat = await r.get(f"bot:{bid}:heartbeat")

                            if info_raw:
                                try:
                                    info = json.loads(info_raw)
                                    last_seen = int(time.time() - float(last_heartbeat or 0))
                                    bots.append({
                                        "bot_id": bid,
                                        "hostname": info.get("hostname", "unknown"),
                                        "status": "online" if last_seen < 60 else "offline",
                                        "last_seen_sec": last_seen,
                                        "cpu": info.get("cpu"),
                                        "memory_gb": info.get("memory_gb")
                                    })
                                except:
                                    pass

                        await ws.send(json.dumps({
                            "type": "result",
                            "data": {"bots": bots, "count": len(bots)}
                        }))

                    else:
                        # Normale Tasks in Redis Queue
                        command = {
                            "task_id": task_id,
                            "action": action,
                            "target": data.get("target", "all"),
                            "payload": data.get("payload")
                        }
                        sent = await self.broadcast_task(command, data.get("target", "all"))

                        await ws.send(json.dumps({
                            "type": "info",
                            "message": f"Task {task_id} an {sent} Bot(s) gesendet."
                        }))

        except Exception as e:
            logging.error(f"Controller connection error: {e}")

    async def main(self):
        print("🚀 MeshCompute Server (Redis + WebSocket) gestartet")
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            await asyncio.Future()  # läuft ewig


if __name__ == "__main__":
    server = MeshServer()
    asyncio.run(server.main())