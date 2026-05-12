from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class Message:
    type: str                    # register, heartbeat, command, result, error
    bot_id: Optional[str] = None
    task_id: Optional[str] = None
    data: Any = None