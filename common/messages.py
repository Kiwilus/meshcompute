from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class Message:
    type: str                    # register, heartbeat, command, result, error
    bot_id: Optional[str] = None
    task_id: Optional[str] = None
    data: Any = None

def create_command(action: str, target: str = "all", payload=None, task_id=None):
    return {
        "type": "command",
        "action": action,
        "target": target,
        "payload": payload,
        "task_id": task_id or str(int(time.time() * 1000))
    }