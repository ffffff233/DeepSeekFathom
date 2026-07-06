from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    content: str
    name: str | None = None
    # data-URL images ("data:image/png;base64,…") for vision. Persisted to the
    # session log so a reloaded conversation (and every follow-up turn, which reloads
    # the session) can still send them to the model.
    images: list[str] = field(default_factory=list)

    def to_api(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        return payload

