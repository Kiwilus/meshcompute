from dataclasses import dataclass, asdict
import json
from typing import Optional, Any

@dataclass
class Message:
    type: str
    token: Optional[str] = None
    role: Optional[str] = None
    bot_id: Optional[str] = None
    task_id: Optional[str] = None
    code: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None

    def to_json(self) -> str:
        data = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        data = json.loads(raw)
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)