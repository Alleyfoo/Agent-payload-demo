from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class RunContext:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    request_ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    params_snapshot: Dict[str, Any] = field(default_factory=dict)
    artifact_snapshot: Optional[Dict[str, Any]] = None
    workspace_dir: Optional[str] = None
    notes: list = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
