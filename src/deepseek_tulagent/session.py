from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from .messages import Message


@dataclass
class Session:
    workspace: Path
    session_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    messages: list[Message] = field(default_factory=list)
    storage_path: Path | None = None

    @property
    def path(self) -> Path:
        if self.storage_path is not None:
            return self.storage_path
        return self.workspace / ".deepseek-tulagent" / "sessions" / f"{self.session_id}.jsonl"

    def append(self, message: Message) -> None:
        self.messages.append(message)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {"session_id": self.session_id, "created_at": self.created_at, "message": asdict(message)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


class SessionStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.sessions_dir = self.workspace / ".deepseek-tulagent" / "sessions"

    def list(self) -> list[dict]:
        if not self.sessions_dir.exists():
            return []
        rows: list[dict] = []
        for path in sorted(self.sessions_dir.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            loaded = self.load(path.stem)
            first_user = next((message.content for message in loaded.messages if message.role == "user"), "")
            rows.append(
                {
                    "session_id": loaded.session_id,
                    "created_at": loaded.created_at,
                    "path": str(path),
                    "messages": len(loaded.messages),
                    "title": first_user[:80],
                }
            )
        return rows

    def load(self, session_id: str) -> Session:
        path = self.resolve_session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        session = Session(self.workspace, session_id=session_id, storage_path=path)
        session.messages.clear()
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("created_at"):
                    session.created_at = event["created_at"]
                message = event.get("message") or {}
                session.messages.append(
                    Message(
                        role=message["role"],
                        content=message.get("content", ""),
                        name=message.get("name"),
                    )
                )
        return session

    def resolve_session_path(self, session_id: str) -> Path:
        candidates = [
            self.sessions_dir / f"{session_id}.jsonl",
            Path.home() / ".deepseek-tulagent" / "sessions" / f"{session_id}.jsonl",
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]
