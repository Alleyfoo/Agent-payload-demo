"""Append-only event log — the audit trail of the agent pipeline.

Every agent action (read, write, validate) appends one event. Events are
written as JSONL (one JSON object per line) to ``data/events_{run_id}.jsonl``
and kept in memory for the UI to read back. The log is append-only: there is
no update, no delete — only append. That is the whole integrity story.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class Event:
    """One audit-trail entry."""

    run_id: str
    agent: str
    action: str
    input_keys: List[str] = field(default_factory=list)
    output_keys: List[str] = field(default_factory=list)
    status: str = "ok"  # ok | warn | error
    checks: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    event_id: str = ""       # assigned on append (evt_NNN)
    timestamp: str = ""      # assigned on append (ISO-8601, +00:00)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventLog:
    """Append-only JSONL writer + in-memory read-back.

    The on-disk file is opened in append mode and flushed on every line so a
    crash mid-run still leaves a complete trail up to the last action.
    """

    def __init__(self, run_id: str, data_dir: str = "data") -> None:
        self.run_id = run_id
        self._events: List[Event] = []
        self._counter = 0
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, f"events_{run_id}.jsonl")
        # Start a fresh file per run.
        self._fh = open(self._path, "a", encoding="utf-8")

    # -- append ----------------------------------------------------------
    def append(self, event: Event) -> Event:
        """Assign ``event_id`` + ``timestamp``, persist, and store."""
        self._counter += 1
        event.event_id = f"evt_{self._counter:03d}"
        if not event.timestamp:
            event.timestamp = datetime.now(timezone.utc).isoformat()
        line = json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False)
        self._fh.write(line + "\n")
        self._fh.flush()
        self._events.append(event)
        return event

    # -- read-back -------------------------------------------------------
    def all(self) -> List[Event]:
        return list(self._events)

    def for_run(self, run_id: str) -> List[Event]:
        return [e for e in self._events if e.run_id == run_id]

    def as_dicts(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._events]

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._events)

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    @classmethod
    def read_file(cls, path: str) -> List[Dict[str, Any]]:
        """Read back a JSONL event file (for UI/tests)."""
        events: List[Dict[str, Any]] = []
        if not os.path.exists(path):
            return events
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events