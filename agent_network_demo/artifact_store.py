"""Shared artifact store: agents register and read artifacts *by key*.

The whole point of the demo: an agent never hands another agent a blob of
content. It hands a *key* (a reference) into this store. The store is the
shared memory; the envelope between agents carries only the keys.

An artifact is a dict shaped like::

    {
        "type": "table_preview",
        "status": "ok",            # ok | pending | warn | error
        ...payload...,
        "source_hash": "<sha256 of canonical JSON>",
    }

The store is in-memory but can snapshot to / hydrate from JSON for tests and
future persistence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


def _canonical(obj: Any) -> str:
    """Deterministic JSON serialization: sorted keys, no whitespace.

    Used both for stable ``source_hash`` values and for snapshots.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_source_hash(artifact: Dict[str, Any]) -> str:
    """sha256 of the canonical JSON of *the payload* (content), not the hash
    field itself — otherwise the hash would be self-referential.
    """
    payload = {k: v for k, v in artifact.items() if k != "source_hash"}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class DuplicateKeyError(KeyError):
    """Raised when a key is re-registered with different content.

    Re-registering the *same* content (same hash) is a no-op — idempotent —
    which lets an agent be safely re-run.
    """


@dataclass
class ArtifactStore:
    """In-memory registry of named artifacts, keyed by dotted string keys
    like ``artifact.raw_input``.

    The store owns the ``source_hash`` field: callers pass content, the store
    stamps the hash. This keeps hashes consistent and tamper-evident.
    """

    _artifacts: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # -- write -----------------------------------------------------------
    def register(self, key: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Store ``artifact`` under ``key`` after stamping its ``source_hash``.

        Re-registering the same key with identical content is idempotent
        (returns the stored artifact). Re-registering with *different*
        content raises :class:`DuplicateKeyError` — keys are immutable
        references once established.
        """
        if not isinstance(artifact, dict):
            raise TypeError("artifact must be a dict")
        if "type" not in artifact:
            raise ValueError(f"artifact for {key!r} missing required 'type' field")

        stored = {**artifact, "source_hash": compute_source_hash(artifact)}
        existing = self._artifacts.get(key)
        if existing is not None:
            if existing["source_hash"] != stored["source_hash"]:
                raise DuplicateKeyError(
                    f"key {key!r} already registered with different content "
                    f"(existing hash {existing['source_hash'][:8]}…, "
                    f"new hash {stored['source_hash'][:8]}…)"
                )
            # Same content — idempotent no-op.
            return existing

        self._artifacts[key] = stored
        return stored

    def set_status(self, key: str, status: str) -> Dict[str, Any]:
        """Update only the ``status`` field of an existing artifact.

        This is the one allowed mutation: status transitions (pending → ok,
        etc.) do not change the content the hash commits to.
        """
        if key not in self._artifacts:
            raise KeyError(key)
        self._artifacts[key]["status"] = status
        return self._artifacts[key]

    # -- read ------------------------------------------------------------
    def get(self, key: str) -> Dict[str, Any]:
        """Return the artifact for ``key`` or raise :class:`KeyError`."""
        try:
            return self._artifacts[key]
        except KeyError:
            raise KeyError(key)

    def has(self, key: str) -> bool:
        return key in self._artifacts

    def keys(self) -> List[str]:
        return list(self._artifacts.keys())

    def as_dict(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._artifacts.items()}

    def __contains__(self, key: str) -> bool:  # pragma: no cover - trivial
        return key in self._artifacts

    def __iter__(self) -> Iterator[str]:  # pragma: no cover - trivial
        return iter(self._artifacts)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._artifacts)

    # -- snapshot (for tests / future persistence) ----------------------
    def to_snapshot(self) -> Dict[str, Dict[str, Any]]:
        return self.as_dict()

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Dict[str, Any]]) -> "ArtifactStore":
        store = cls()
        for key, artifact in snapshot.items():
            store._artifacts[key] = dict(artifact)
        return store

    def summary(self) -> List[Dict[str, Any]]:
        """A compact, UI-friendly listing: one entry per artifact."""
        return [
            {"key": k, "type": v.get("type"), "status": v.get("status"),
             "source_hash": v.get("source_hash")}
            for k, v in self._artifacts.items()
        ]

    def view(self, read_keys: List[str], write_key: str = "") -> "StoreView":
        """Return a capability-scoped handle: a caller may read only the keys
        in ``read_keys`` and write only ``write_key``. This is what the runner
        hands an agent — the envelope's ``input_keys`` become the read grant
        and its ``output_contract``'s key becomes the write grant, so an agent
        literally cannot reach for a key it was not handed."""
        return StoreView(self, read_keys=read_keys, write_key=write_key)


class StoreView:
    """A capability-scoped handle to an :class:`ArtifactStore`.

    The whole "keys not blobs" mechanism: an agent receives one of these
    instead of the raw store. It may ``get`` only the keys it was granted
    (the inbound envelope's ``input_keys``) and ``register`` only the single
    key its ``output_contract`` licenses. Anything else raises
    :class:`agent_network_demo.contracts.ContractError` — the same error the
    runner already catches — so the envelope is a *capability token*, not a
    label. Without this gate every agent could read the entire store, which is
    what made the original "passing keys" merely decorative.
    """

    def __init__(self, store: "ArtifactStore", read_keys: List[str],
                 write_key: str = "") -> None:
        self._store = store
        self._read_keys = set(read_keys)
        self._write_key = write_key

    @staticmethod
    def _contract_error(msg: str):
        # Lazy import: contracts.py imports ArtifactStore from this module, so
        # importing ContractError at module top would be circular.
        from agent_network_demo.contracts import ContractError
        return ContractError(msg)

    def get(self, key: str) -> Dict[str, Any]:
        """Return the artifact for a *granted* key, or raise. Reading a key
        that was not handed to this view is a contract violation."""
        if key not in self._read_keys:
            raise self._contract_error(
                f"read of {key!r} denied: not in this envelope's input_keys "
                f"(granted {sorted(self._read_keys)})"
            )
        return self._store.get(key)

    def has(self, key: str) -> bool:
        """True only if the key is granted AND present — an agent cannot probe
        for keys it was not handed."""
        return key in self._read_keys and self._store.has(key)

    def register(self, key: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Store ``artifact`` under ``key`` only if ``key`` is this view's
        contracted write key. Writing anything else is a contract violation."""
        if self._write_key and key != self._write_key:
            raise self._contract_error(
                f"write of {key!r} denied: this envelope's output_contract "
                f"only licenses writing {self._write_key!r}"
            )
        if not self._write_key and key:
            raise self._contract_error(
                f"write of {key!r} denied: this envelope declared no "
                "output_contract"
            )
        return self._store.register(key, artifact)