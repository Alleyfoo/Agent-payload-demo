"""Tests for the shared artifact store: the 'keys not blobs' shared memory."""

from __future__ import annotations

import pytest

from agent_network_demo.artifact_store import (
    ArtifactStore,
    DuplicateKeyError,
    compute_source_hash,
)


def test_register_stamps_source_hash_and_returns_copy():
    store = ArtifactStore()
    art = store.register("artifact.x", {"type": "table_preview", "status": "ok",
                                         "rows": 3})
    assert "source_hash" in art
    assert art["source_hash"] == compute_source_hash(
        {"type": "table_preview", "status": "ok", "rows": 3})
    assert store.has("artifact.x")


def test_get_missing_raises_keyerror():
    store = ArtifactStore()
    with pytest.raises(KeyError):
        store.get("nope")


def test_register_idempotent_same_content():
    store = ArtifactStore()
    a = store.register("artifact.x", {"type": "t", "status": "ok"})
    b = store.register("artifact.x", {"type": "t", "status": "ok"})
    assert a["source_hash"] == b["source_hash"]
    assert len(store) == 1


def test_register_different_content_raises():
    store = ArtifactStore()
    store.register("artifact.x", {"type": "t", "status": "ok"})
    with pytest.raises(DuplicateKeyError):
        store.register("artifact.x", {"type": "t", "status": "warn"})


def test_register_requires_type_field():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.register("artifact.x", {"status": "ok"})


def test_artifact_reads_are_deeply_immutable():
    store = ArtifactStore()
    store.register("artifact.x", {"type": "t", "status": "ok",
                                   "nested": {"items": [1, 2]}})
    original_hash = store.get("artifact.x")["source_hash"]
    returned = store.get("artifact.x")
    returned["nested"]["items"].append(3)
    assert store.get("artifact.x")["nested"]["items"] == [1, 2]
    assert store.get("artifact.x")["source_hash"] == original_hash


def test_snapshot_hydration_rejects_invalid_hash():
    store = ArtifactStore()
    store.register("artifact.x", {"type": "t", "nested": {"x": 1}})
    snap = store.to_snapshot()
    snap["artifact.x"]["nested"]["x"] = 2
    with pytest.raises(ValueError, match="invalid source_hash"):
        ArtifactStore.from_snapshot(snap)


def test_keys_as_dict_and_summary():
    store = ArtifactStore()
    store.register("artifact.a", {"type": "t", "status": "ok"})
    store.register("artifact.b", {"type": "t", "status": "ok"})
    assert set(store.keys()) == {"artifact.a", "artifact.b"}
    d = store.as_dict()
    assert set(d.keys()) == {"artifact.a", "artifact.b"}
    assert all("source_hash" in v for v in d.values())
    summary = store.summary()
    assert {e["key"] for e in summary} == {"artifact.a", "artifact.b"}


def test_snapshot_roundtrip():
    store = ArtifactStore()
    store.register("artifact.a", {"type": "t", "status": "ok"})
    snap = store.to_snapshot()
    store2 = ArtifactStore.from_snapshot(snap)
    assert store2.has("artifact.a")
    assert store2.get("artifact.a")["source_hash"] == \
        store.get("artifact.a")["source_hash"]


def test_source_hash_ignores_source_hash_field():
    """The hash must be computed over content, not over itself."""
    h = compute_source_hash({"type": "t", "status": "ok"})
    h2 = compute_source_hash(
        {"type": "t", "status": "ok", "source_hash": "anything"})
    assert h == h2
