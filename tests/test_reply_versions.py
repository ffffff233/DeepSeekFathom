from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
import time
from types import MappingProxyType

import pytest

from deepseekfathom._core.messages import Message
from deepseekfathom._core.reply_versions import (
    CorruptReplyVersionDocumentError,
    ReplyVersionStore,
    ReplyVersionStoreError,
    snapshot_record,
)


VERSION_ONE = "1" * 32
VERSION_TWO = "2" * 32


def _message(label: str = "answer") -> Message:
    return Message(
        role="assistant",
        content=label,
        name="writer",
        images=["data:image/png;base64,AAAA"],
        ui_kind="reply",
        display_content=f"shown {label}",
        model_visible=False,
        turn_id="turn-7",
    )


def test_reply_snapshot_survives_restart_with_every_message_field(tmp_path: Path) -> None:
    store = ReplyVersionStore(tmp_path)
    stored = store.put(
        "session-1",
        VERSION_ONE,
        [_message()],
        {"parentVersionId": None, "nested": {"score": 3}},
        set_active=True,
    )
    store.set_graph("session-1", {"rootVersionId": VERSION_ONE, "order": [VERSION_ONE]})

    assert stored == {"messages": [_message()], "metadata": {"parentVersionId": None, "nested": {"score": 3}}}

    restarted = ReplyVersionStore(tmp_path)
    assert restarted.get("session-1", VERSION_ONE) == stored
    assert restarted.get_active("session-1") == VERSION_ONE
    assert restarted.get_active_snapshot("session-1") == stored
    assert restarted.get_graph("session-1") == {
        "rootVersionId": VERSION_ONE,
        "order": [VERSION_ONE],
    }

    raw = json.loads(restarted.document_path("session-1").read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 1
    assert raw["sessionId"] == "session-1"
    assert raw["snapshots"][VERSION_ONE]["messages"][0] == {
        "role": "assistant",
        "content": "answer",
        "name": "writer",
        "images": ["data:image/png;base64,AAAA"],
        "ui_kind": "reply",
        "display_content": "shown answer",
        "model_visible": False,
        "turn_id": "turn-7",
    }


def test_put_keeps_every_version_and_returns_detached_values(tmp_path: Path) -> None:
    store = ReplyVersionStore(tmp_path)
    for index in range(150):
        store.put("many", f"{index:032x}", [_message(str(index))], {"index": index})

    document = store.load_document("many")
    assert len(document["snapshots"]) == 150
    document["snapshots"].clear()
    loaded = store.get("many", "0" * 32)
    assert loaded is not None
    loaded["messages"][0].images.append("mutated")
    loaded["metadata"]["index"] = 999
    assert store.get("many", "0" * 32) == {
        "messages": [_message("0")],
        "metadata": {"index": 0},
    }


def test_document_update_is_locked_across_store_instances(tmp_path: Path) -> None:
    stores = [ReplyVersionStore(tmp_path), ReplyVersionStore(tmp_path)]

    def add_versions(worker: int) -> None:
        for index in range(30):
            version_id = f"{worker * 100 + index + 1:032x}"

            def update(document: dict, version_id: str = version_id) -> None:
                current = len(document["snapshots"])
                time.sleep(0.001)
                document["snapshots"][version_id] = {
                    "messages": [],
                    "metadata": {"observedCount": current},
                }

            stores[worker].update_document("concurrent", update)

    threads = [Thread(target=add_versions, args=(worker,)) for worker in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(stores[0].load_document("concurrent")["snapshots"]) == 60


def test_snapshot_record_supports_multi_snapshot_document_update(tmp_path: Path) -> None:
    store = ReplyVersionStore(tmp_path)

    def update(document: dict) -> None:
        document["snapshots"][VERSION_ONE] = snapshot_record([_message("one")], {"index": 1})
        document["snapshots"][VERSION_TWO] = snapshot_record([_message("two")], {"index": 2})
        document["activeVersionId"] = VERSION_TWO
        document["graph"] = {"order": [VERSION_ONE, VERSION_TWO]}

    store.update_document("batch", update)

    assert store.get("batch", VERSION_ONE) == {
        "messages": [_message("one")],
        "metadata": {"index": 1},
    }
    assert store.get_active("batch") == VERSION_TWO
    assert store.get_graph("batch") == {"order": [VERSION_ONE, VERSION_TWO]}


def test_mapping_inputs_are_normalized_and_falsey_non_objects_are_rejected(tmp_path: Path) -> None:
    record = snapshot_record([], MappingProxyType({"nested": MappingProxyType({"ok": True})}))
    assert record == {"messages": [], "metadata": {"nested": {"ok": True}}}
    with pytest.raises(TypeError, match="snapshot metadata must be an object"):
        snapshot_record([], [])  # type: ignore[arg-type]

    store = ReplyVersionStore(tmp_path)
    replacement = MappingProxyType(
        {
            "schemaVersion": 1,
            "sessionId": "mapping",
            "snapshots": MappingProxyType({VERSION_ONE: MappingProxyType(record)}),
            "activeVersionId": VERSION_ONE,
            "graph": MappingProxyType({"active": VERSION_ONE}),
        }
    )
    store.update_document("mapping", lambda _document: replacement)
    assert store.get_active("mapping") == VERSION_ONE


def test_failed_atomic_replace_preserves_previous_document(monkeypatch, tmp_path: Path) -> None:
    store = ReplyVersionStore(tmp_path)
    store.put("atomic", VERSION_ONE, [_message("old")])
    path = store.document_path("atomic")
    before = path.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr("deepseekfathom._core.reply_versions.os.replace", fail_replace)
    with pytest.raises(ReplyVersionStoreError, match="could not write"):
        store.put("atomic", VERSION_TWO, [_message("new")])

    assert path.read_bytes() == before
    assert not list(path.parent.glob(f".{path.name}.tmp-*"))


def test_temporary_file_creation_error_uses_store_error(monkeypatch, tmp_path: Path) -> None:
    store = ReplyVersionStore(tmp_path)

    def fail_mkstemp(**_kwargs) -> tuple[int, str]:
        raise OSError("disk unavailable")

    monkeypatch.setattr("deepseekfathom._core.reply_versions.tempfile.mkstemp", fail_mkstemp)
    with pytest.raises(ReplyVersionStoreError, match="could not write"):
        store.put("atomic", VERSION_ONE, [])
    assert not store.document_path("atomic").exists()


def test_active_graph_delete_and_missing_behavior(tmp_path: Path) -> None:
    store = ReplyVersionStore(tmp_path)
    assert store.load_document("new") == {
        "schemaVersion": 1,
        "sessionId": "new",
        "snapshots": {},
        "activeVersionId": None,
        "graph": {},
    }
    assert store.get("new", VERSION_ONE) is None
    with pytest.raises(KeyError, match="reply version not found"):
        store.set_active("new", VERSION_ONE)

    store.put("new", VERSION_ONE, [])
    assert store.set_active("new", VERSION_ONE) == VERSION_ONE
    assert store.delete("new", VERSION_ONE) is True
    assert store.get_active("new") is None
    assert store.delete("new", VERSION_ONE) is False
    assert store.delete_session("new") is True
    assert store.delete_session("new") is False


@pytest.mark.parametrize("invalid", ["", ".", "..", "../escape", "a/b", "a\\b", " space", "x" * 129])
def test_session_ids_are_validated(tmp_path: Path, invalid: str) -> None:
    store = ReplyVersionStore(tmp_path)
    with pytest.raises(ValueError, match="invalid session id"):
        store.load_document(invalid)


@pytest.mark.parametrize(
    "invalid",
    ["", "version-1", "A" * 32, "12345678-1234-1234-1234-123456789abc", "f" * 31, "f" * 33, 12, None],
)
def test_version_ids_are_validated(tmp_path: Path, invalid: object) -> None:
    store = ReplyVersionStore(tmp_path)
    with pytest.raises(ValueError, match="invalid reply version id"):
        store.put("valid", invalid, [])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"schemaVersion":1.0,"sessionId":"broken","snapshots":{},"activeVersionId":null,"graph":{}}',
        '{"schemaVersion":1,"sessionId":"other","snapshots":{},"activeVersionId":null,"graph":{}}',
        '{"schemaVersion":1,"sessionId":"broken","snapshots":{},"activeVersionId":"missing","graph":{}}',
        '{"schemaVersion":1,"sessionId":"broken","snapshots":{},"activeVersionId":null,"graph":{},"graph":{}}',
    ],
)
def test_corrupt_documents_fail_without_being_overwritten(tmp_path: Path, payload: str) -> None:
    store = ReplyVersionStore(tmp_path)
    path = store.document_path("broken")
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(CorruptReplyVersionDocumentError):
        store.load_document("broken")
    with pytest.raises(CorruptReplyVersionDocumentError):
        store.put("broken", VERSION_ONE, [])
    assert path.read_text(encoding="utf-8") == payload


def test_update_document_validates_before_writing(tmp_path: Path) -> None:
    store = ReplyVersionStore(tmp_path)

    def invalid(document: dict) -> None:
        document["graph"] = {"bad": float("nan")}

    with pytest.raises(ValueError, match="non-finite"):
        store.update_document("validation", invalid)
    assert not store.document_path("validation").exists()
