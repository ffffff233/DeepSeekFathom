from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    content: str
    name: str | None = None
    # data-URL images ("data:image/png;base64,…") for vision on the live turn only;
    # NOT persisted to the session log (stripped in Session.append/rewrite)
    images: list[str] = field(default_factory=list)

    def to_api(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        return payload

