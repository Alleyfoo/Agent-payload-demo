"""Immutable shared artifacts accessed through capability-scoped views."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_source_hash(artifact: Dict[str, Any]) -> str:
    payload = {k: v for k, v in artifact.items() if k != "source_hash"}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class DuplicateKeyError(KeyError):
    """Raised when an immutable key is reused for different content."""


@dataclass
class ArtifactStore:
    """In-memory registry whose public reads always return deep copies."""

    _artifacts: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def register(self, key: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(artifact, dict):
            raise TypeError("artifact must be a dict")
        if "type" not in artifact:
            raise ValueError(f"artifact for {key!r} missing required 'type' field")

        content = deepcopy(artifact)
        stored = {**content, "source_hash": compute_source_hash(content)}
        existing = self._artifacts.get(key)
        if existing is not None:
            if existing["source_hash"] != stored["source_hash"]:
                raise DuplicateKeyError(
                    f"key {key!r} already registered with different content "
                    f"(existing hash {existing['source_hash'][:8]}..., "
                    f"new hash {stored['source_hash'][:8]}...)"
                )
            return deepcopy(existing)

        self._artifacts[key] = stored
        return deepcopy(stored)

    def get(self, key: str) -> Dict[str, Any]:
        try:
            return deepcopy(self._artifacts[key])
        except KeyError:
            raise KeyError(key)

    def has(self, key: str) -> bool:
        return key in self._artifacts

    def keys(self) -> List[str]:
        return list(self._artifacts.keys())

    def as_dict(self) -> Dict[str, Dict[str, Any]]:
        return deepcopy(self._artifacts)

    def __contains__(self, key: str) -> bool:
        return key in self._artifacts

    def __iter__(self) -> Iterator[str]:
        return iter(self._artifacts)

    def __len__(self) -> int:
        return len(self._artifacts)

    def to_snapshot(self) -> Dict[str, Dict[str, Any]]:
        return self.as_dict()

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Dict[str, Any]]) -> "ArtifactStore":
        store = cls()
        for key, artifact in snapshot.items():
            if not isinstance(artifact, dict) or "source_hash" not in artifact:
                raise ValueError(f"snapshot artifact {key!r} missing source_hash")
            if artifact["source_hash"] != compute_source_hash(artifact):
                raise ValueError(f"snapshot artifact {key!r} has invalid source_hash")
            store._artifacts[key] = deepcopy(artifact)
        return store

    def summary(self) -> List[Dict[str, Any]]:
        return [
            {"key": key, "type": value.get("type"), "status": value.get("status"),
             "source_hash": value.get("source_hash")}
            for key, value in self._artifacts.items()
        ]

    def view(self, read_keys: List[str], write_key: str = "") -> "StoreView":
        return StoreView(self, read_keys=read_keys, write_key=write_key)


class StoreView:
    """Capability-scoped store handle that records actual reads and writes."""

    def __init__(self, store: ArtifactStore, read_keys: List[str],
                 write_key: str = "") -> None:
        self._store = store
        self._read_grants = set(read_keys)
        self._write_grant = write_key
        self._read_log: List[str] = []
        self._write_log: List[str] = []

    @property
    def read_keys(self) -> List[str]:
        return list(self._read_log)

    @property
    def written_keys(self) -> List[str]:
        return list(self._write_log)

    @staticmethod
    def _contract_error(message: str):
        from agent_network_demo.contracts import ContractError
        return ContractError(message)

    def get(self, key: str) -> Dict[str, Any]:
        if key not in self._read_grants:
            raise self._contract_error(
                f"read of {key!r} denied: granted {sorted(self._read_grants)}"
            )
        self._read_log.append(key)
        return self._store.get(key)

    def has(self, key: str) -> bool:
        return key in self._read_grants and self._store.has(key)

    def register(self, key: str, artifact: Dict[str, Any]) -> Dict[str, Any]:
        if not self._write_grant:
            raise self._contract_error(
                f"write of {key!r} denied: this envelope declared no output_contract"
            )
        if key != self._write_grant:
            raise self._contract_error(
                f"write of {key!r} denied: granted {self._write_grant!r}"
            )
        result = self._store.register(key, artifact)
        self._write_log.append(key)
        return result
