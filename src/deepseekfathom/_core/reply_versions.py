from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from .config import DATA_DIRNAME
from .messages import Message
from .session import validate_session_id


SCHEMA_VERSION = 1
_VERSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ROLES = {"system", "user", "assistant", "tool"}

_LOCKS_GUARD = threading.Lock()
_DOCUMENT_LOCKS: dict[Path, threading.RLock] = {}


class ReplyVersionStoreError(RuntimeError):
    """Base error raised by the reply-version persistence layer."""


class CorruptReplyVersionDocumentError(ReplyVersionStoreError):
    """Raised when a persisted reply-version document cannot be trusted."""


def validate_version_id(version_id: str) -> str:
    if not isinstance(version_id, str) or not _VERSION_ID_RE.fullmatch(version_id):
        raise ValueError("invalid reply version id")
    return version_id


class ReplyVersionStore:
    """Persist complete reply snapshots and their version graph per session.

    Each session is stored in one atomically replaced JSON document. The store never
    prunes snapshots; a snapshot disappears only when a caller explicitly removes it
    through ``update_document`` or deletes the whole session document.
    """

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.versions_dir = self.workspace / DATA_DIRNAME / "reply_versions"

    def document_path(self, session_id: str) -> Path:
        session_id = validate_session_id(session_id)
        return self.versions_dir / f"{session_id}.json"

    def load_document(self, session_id: str) -> dict[str, Any]:
        """Return a detached JSON-shaped document, or a new empty document."""

        session_id = validate_session_id(session_id)
        path = self.document_path(session_id)
        with _document_lock(path):
            return self._load_document_unlocked(session_id, path)

    def update_document(
        self,
        session_id: str,
        updater: Callable[[dict[str, Any]], Mapping[str, Any] | None],
    ) -> dict[str, Any]:
        """Atomically apply a read-modify-write operation to one session document.

        ``updater`` receives a detached mutable document. It may mutate that document
        and return ``None``, or return a replacement mapping. The result is validated
        in full before the existing file is replaced.
        """

        session_id = validate_session_id(session_id)
        if not callable(updater):
            raise TypeError("updater must be callable")
        path = self.document_path(session_id)
        with _document_lock(path):
            current = self._load_document_unlocked(session_id, path)
            working = deepcopy(current)
            replacement = updater(working)
            candidate: Mapping[str, Any] = working if replacement is None else replacement
            document = _validate_document(candidate, session_id)
            _atomic_write_json(path, document)
            return deepcopy(document)

    def put(
        self,
        session_id: str,
        version_id: str,
        messages: Iterable[Message],
        metadata: Mapping[str, Any] | None = None,
        *,
        set_active: bool = False,
    ) -> dict[str, Any]:
        """Create or replace one snapshot without affecting any other version."""

        session_id = validate_session_id(session_id)
        version_id = validate_version_id(version_id)
        record = snapshot_record(messages, metadata)

        def update(document: dict[str, Any]) -> None:
            document["snapshots"][version_id] = deepcopy(record)
            if set_active:
                document["activeVersionId"] = version_id

        document = self.update_document(session_id, update)
        return _snapshot_from_record(document["snapshots"][version_id])

    def get(self, session_id: str, version_id: str) -> dict[str, Any] | None:
        """Load one snapshot as ``Message`` objects and detached metadata."""

        version_id = validate_version_id(version_id)
        document = self.load_document(session_id)
        snapshot = document["snapshots"].get(version_id)
        return _snapshot_from_record(snapshot) if snapshot is not None else None

    def delete(self, session_id: str, version_id: str) -> bool:
        """Explicitly delete one snapshot and clear active state when necessary."""

        version_id = validate_version_id(version_id)
        removed = False

        def update(document: dict[str, Any]) -> None:
            nonlocal removed
            removed = document["snapshots"].pop(version_id, None) is not None
            if document["activeVersionId"] == version_id:
                document["activeVersionId"] = None

        self.update_document(session_id, update)
        return removed

    def set_active(self, session_id: str, version_id: str | None) -> str | None:
        """Select an existing snapshot, or clear the active version with ``None``."""

        validated = None if version_id is None else validate_version_id(version_id)

        def update(document: dict[str, Any]) -> None:
            if validated is not None and validated not in document["snapshots"]:
                raise KeyError(f"reply version not found: {validated}")
            document["activeVersionId"] = validated

        self.update_document(session_id, update)
        return validated

    def get_active(self, session_id: str) -> str | None:
        return self.load_document(session_id)["activeVersionId"]

    def get_active_snapshot(self, session_id: str) -> dict[str, Any] | None:
        document = self.load_document(session_id)
        active = document["activeVersionId"]
        if active is None:
            return None
        return _snapshot_from_record(document["snapshots"][active])

    def set_graph(self, session_id: str, graph: Mapping[str, Any]) -> dict[str, Any]:
        value = _validate_json_object(graph, "graph metadata")

        def update(document: dict[str, Any]) -> None:
            document["graph"] = deepcopy(value)

        document = self.update_document(session_id, update)
        return deepcopy(document["graph"])

    def get_graph(self, session_id: str) -> dict[str, Any]:
        return deepcopy(self.load_document(session_id)["graph"])

    def delete_session(self, session_id: str) -> bool:
        session_id = validate_session_id(session_id)
        path = self.document_path(session_id)
        with _document_lock(path):
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise ReplyVersionStoreError(
                    f"could not delete reply-version document for session {session_id}"
                ) from exc
            return True

    def _load_document_unlocked(self, session_id: str, path: Path) -> dict[str, Any]:
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _empty_document(session_id)
        except (OSError, UnicodeError) as exc:
            raise CorruptReplyVersionDocumentError(
                f"could not read reply-version document for session {session_id}"
            ) from exc

        try:
            raw = json.loads(source, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
            raise CorruptReplyVersionDocumentError(
                f"invalid reply-version JSON for session {session_id}"
            ) from exc
        try:
            return _validate_document(raw, session_id)
        except (TypeError, ValueError) as exc:
            raise CorruptReplyVersionDocumentError(
                f"invalid reply-version document for session {session_id}: {exc}"
            ) from exc


def _empty_document(session_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "snapshots": {},
        "activeVersionId": None,
        "graph": {},
    }


def snapshot_record(
    messages: Iterable[Message],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a validated JSON snapshot for use inside ``update_document``."""

    records = [_message_to_record(message) for message in messages]
    # Round-trip through the strict decoder so callers cannot inject an invalid
    # Message instance whose runtime values disagree with its type annotations.
    normalized = [_message_to_record(_message_from_record(record)) for record in records]
    return {
        "messages": normalized,
        "metadata": _validate_json_object({} if metadata is None else metadata, "snapshot metadata"),
    }


def _validate_document(raw: Mapping[str, Any], session_id: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("document must be an object")
    expected_keys = {"schemaVersion", "sessionId", "snapshots", "activeVersionId", "graph"}
    if set(raw) != expected_keys:
        raise ValueError("document keys do not match the schema")
    if type(raw["schemaVersion"]) is not int or raw["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError("unsupported schemaVersion")
    if raw["sessionId"] != session_id:
        raise ValueError("sessionId does not match its storage record")

    snapshots_raw = raw["snapshots"]
    if not isinstance(snapshots_raw, Mapping):
        raise TypeError("snapshots must be an object")
    snapshots: dict[str, Any] = {}
    for version_id, snapshot in snapshots_raw.items():
        validate_version_id(version_id)
        if not isinstance(snapshot, Mapping) or set(snapshot) != {"messages", "metadata"}:
            raise ValueError(f"snapshot {version_id!r} does not match the schema")
        messages_raw = snapshot["messages"]
        if not isinstance(messages_raw, list):
            raise TypeError(f"snapshot {version_id!r} messages must be an array")
        messages = [_message_to_record(_message_from_record(item)) for item in messages_raw]
        metadata = _validate_json_object(snapshot["metadata"], f"snapshot {version_id!r} metadata")
        snapshots[version_id] = {"messages": messages, "metadata": metadata}

    active = raw["activeVersionId"]
    if active is not None:
        active = validate_version_id(active)
        if active not in snapshots:
            raise ValueError("activeVersionId does not identify a stored snapshot")
    graph = _validate_json_object(raw["graph"], "graph metadata")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "snapshots": snapshots,
        "activeVersionId": active,
        "graph": graph,
    }


def _message_to_record(message: Message) -> dict[str, Any]:
    if not isinstance(message, Message):
        raise TypeError("snapshot messages must be Message instances")
    return {
        "role": message.role,
        "content": message.content,
        "name": message.name,
        "images": list(message.images),
        "ui_kind": message.ui_kind,
        "display_content": message.display_content,
        "model_visible": message.model_visible,
        "turn_id": message.turn_id,
    }


def _message_from_record(raw: Any) -> Message:
    if not isinstance(raw, dict):
        raise TypeError("message must be an object")
    expected_keys = {
        "role",
        "content",
        "name",
        "images",
        "ui_kind",
        "display_content",
        "model_visible",
        "turn_id",
    }
    if set(raw) != expected_keys:
        raise ValueError("message fields do not match the Message schema")
    role = raw["role"]
    content = raw["content"]
    name = raw["name"]
    images = raw["images"]
    ui_kind = raw["ui_kind"]
    display_content = raw["display_content"]
    model_visible = raw["model_visible"]
    turn_id = raw["turn_id"]
    if not isinstance(role, str) or role not in _ROLES:
        raise ValueError("invalid message role")
    if not isinstance(content, str):
        raise TypeError("message content must be a string")
    for field_name, value in (
        ("name", name),
        ("ui_kind", ui_kind),
        ("display_content", display_content),
        ("turn_id", turn_id),
    ):
        if value is not None and not isinstance(value, str):
            raise TypeError(f"message {field_name} must be a string or null")
    if not isinstance(images, list) or any(not isinstance(image, str) for image in images):
        raise TypeError("message images must be an array of strings")
    if not isinstance(model_visible, bool):
        raise TypeError("message model_visible must be a boolean")
    return Message(
        role=role,
        content=content,
        name=name,
        images=list(images),
        ui_kind=ui_kind,
        display_content=display_content,
        model_visible=model_visible,
        turn_id=turn_id,
    )


def _snapshot_from_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "messages": [_message_from_record(message) for message in raw["messages"]],
        "metadata": deepcopy(raw["metadata"]),
    }


def _validate_json_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    normalized = _normalize_json_value(value, label)
    assert isinstance(normalized, dict)
    return normalized


def _normalize_json_value(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        raise ValueError(f"{label} contains a non-finite number")
    if isinstance(value, list):
        return [_normalize_json_value(item, label) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{label} contains a non-string key")
            normalized[key] = _normalize_json_value(item, label)
        return normalized
    raise TypeError(f"{label} contains a value that is not JSON-compatible")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _document_lock(path: Path) -> threading.RLock:
    key = path.resolve(strict=False)
    with _LOCKS_GUARD:
        lock = _DOCUMENT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _DOCUMENT_LOCKS[key] = lock
        return lock


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    try:
        body = json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise ReplyVersionStoreError("reply-version document is not JSON-serializable") from exc

    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
        temporary_path = Path(temporary)
        handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = None
        with handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary_path.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
    except (OSError, UnicodeError) as exc:
        raise ReplyVersionStoreError(f"could not write reply-version document: {path.name}") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
