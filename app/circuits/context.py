from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class ContextState:
    active_artifact: Optional[Any] = None
    artifact_type: Optional[str] = None
    artifact_id: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class ContextStateCircuit:
    """In-memory context for the latest artifact."""

    def __init__(self) -> None:
        self.state = ContextState()

    def set_artifact(self, artifact: Any, artifact_type: str | None = None, schema: Dict[str, Any] | None = None) -> None:
        self.state.active_artifact = artifact
        self.state.artifact_type = artifact_type
        self.state.schema = schema
        self.state.artifact_id = str(datetime.utcnow().timestamp())
        self.state.timestamp = datetime.utcnow().isoformat()

    def has_artifact(self) -> bool:
        return self.state.active_artifact is not None

    def get_state(self) -> ContextState:
        return self.state
