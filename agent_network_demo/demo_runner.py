"""The run session: owns the ordered agent chain and steps it one agent at a
time. This is the only thing the UI talks to.

Responsibilities:
- build the ordered list of agents (Intake → Schema → Transform → Validation)
- validate each envelope inbound (input keys exist) and outbound (writes
  match the declared output_contract) before/after an agent runs
- expose a snapshot after each step: chain status, current envelope, state
  keys, new events
- produce a final human-readable report once the ShadowJudge has acted
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .agents import (
    IntakeAgent,
    SchemaAgent,
    TransformAgent,
    ValidationAgent,
    KEY_CLEANED,
    KEY_RAW_INPUT,
    KEY_SCHEMA,
    KEY_VERDICT,
)
from .artifact_store import ArtifactStore
from .contracts import HandoffEnvelope, ContractError
from .event_log import Event, EventLog


@dataclass
class StepSnapshot:
    """What changed in one step — handed back to the UI."""

    run_id: str
    step_index: int
    agent: str
    chain_status: List[Dict[str, str]]
    envelope: Dict[str, Any]
    state_keys: List[str]
    new_events: List[Dict[str, Any]]
    status: str
    message: str
    done: bool


class RunSession:
    """One interactive run of the agent chain."""

    AGENT_NAMES: Tuple[str, ...] = (
        "intake_agent", "schema_agent", "transform_agent", "validation_agent",
    )

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.run_id: str = ""
        self.store: Optional[ArtifactStore] = None
        self.log: Optional[EventLog] = None
        self._agents: List[Any] = []
        self._current = 0
        self._envelope: Optional[HandoffEnvelope] = None
        self._key_file: Dict[str, Any] = {}
        self._last_snapshot: Optional[StepSnapshot] = None
        self.done = False
        self.error: Optional[str] = None

    # -- lifecycle -------------------------------------------------------
    def start_run(self, key_file_path: str = "fixtures/key_file.json") -> str:
        """Create a run id, load the key file, seed store + log, build the
        ordered agent list, set the seed envelope, and return the run id."""
        if not os.path.exists(key_file_path):
            raise FileNotFoundError(f"key file not found: {key_file_path}")
        with open(key_file_path, "r", encoding="utf-8") as fh:
            self._key_file = json.load(fh)

        # Deterministic, readable run id (no Date.now/random needed for a demo).
        existing = [d for d in os.listdir(self.data_dir)
                    if d.startswith("events_")] if os.path.exists(self.data_dir) else []
        self.run_id = f"run_{len(existing) + 1:03d}"

        self.store = ArtifactStore()
        self.log = EventLog(self.run_id, data_dir=self.data_dir)

        source_ref = self._key_file.get("source_ref", "fixtures/sample_payload.json")
        self._agents = [
            IntakeAgent(source_ref=source_ref),
            SchemaAgent(),
            TransformAgent(),
            ValidationAgent(),
        ]
        self._current = 0
        self.done = False
        self.error = None

        # Seed envelope: nothing in the store yet; intake reads the file.
        self._envelope = HandoffEnvelope(
            run_id=self.run_id,
            from_agent="key_file",
            to_agent="intake_agent",
            handoff_type="intake_request",
            input_keys=[],
            output_contract="table_preview.v1",
            context_summary=self._key_file.get("run_intent", "ingest_orders"),
            allowed_actions=self._key_file.get("allowed_actions", ["read_artifact"]),
        )
        self._last_snapshot = None
        return self.run_id

    # -- stepping --------------------------------------------------------
    def step(self) -> StepSnapshot:
        """Run the current agent and advance. Returns a snapshot of the
        resulting state. Raises :class:`RuntimeError` if the run is done."""
        if self.done:
            raise RuntimeError("run is complete; call reset() to start again")
        if self._current >= len(self._agents):
            self.done = True
            raise RuntimeError("no agent left to run")

        agent = self._agents[self._current]
        envelope = self._envelope
        assert self.store is not None and self.log is not None

        status = "ok"
        message = ""
        event_count_before = len(self.log.all())
        before_keys = set(self.store.keys())
        try:
            # Inbound contract check: declared input keys must exist.
            envelope.validate_inbound(self.store)

            new_envelope = agent.run(envelope, self.store, self.log)

            # Outbound contract check: what did the agent actually write?
            written = [k for k in self.store.keys() if k not in before_keys]
            written_envelope = HandoffEnvelope(
                run_id=envelope.run_id, from_agent=agent.name,
                to_agent=envelope.to_agent, handoff_type=envelope.handoff_type,
                input_keys=envelope.input_keys,
                output_contract=envelope.output_contract,
            )
            written_envelope.validate_outbound(written)

            self._envelope = new_envelope
            self._current += 1
        except ContractError as exc:
            status = "error"
            message = f"contract violation: {exc}"
            self.error = message
            self._emit_error(agent.name, str(exc))
        except Exception as exc:  # noqa: BLE001 - surface to the UI
            status = "error"
            message = f"{type(exc).__name__}: {exc}"
            self.error = message
            self._emit_error(agent.name, message)

        new_events = [e.to_dict() for e in self.log.all()[event_count_before:]]

        if self._current >= len(self._agents):
            self.done = True

        snap = StepSnapshot(
            run_id=self.run_id,
            step_index=self._current,
            agent=agent.name,
            chain_status=self.chain_status(),
            envelope=(self._envelope.to_dict() if self._envelope else {}),
            state_keys=self.store.keys(),
            new_events=new_events,
            status=status,
            message=message or f"{agent.name} ran.",
            done=self.done,
        )
        self._last_snapshot = snap
        return snap

    def _emit_error(self, agent_name: str, message: str) -> None:
        assert self.log is not None
        self.log.append(Event(
            run_id=self.run_id, agent=agent_name, action="error",
            input_keys=[], output_keys=[], status="error",
            checks={}, message=message,
        ))

    def reset(self) -> None:
        """Clear the current run so a new one can start."""
        if self.log is not None:
            self.log.close()
        self.run_id = ""
        self.store = None
        self.log = None
        self._agents = []
        self._current = 0
        self._envelope = None
        self._key_file = {}
        self._last_snapshot = None
        self.done = False
        self.error = None

    # -- read-only views (for the UI) ------------------------------------
    def chain_status(self) -> List[Dict[str, str]]:
        """Per agent: acted | control | waiting."""
        out: List[Dict[str, str]] = []
        for i, name in enumerate(self.AGENT_NAMES):
            if i < self._current:
                state = "acted"
            elif i == self._current and not self.done:
                state = "control"
            else:
                state = "waiting"
            out.append({"agent": name, "state": state})
        return out

    def state(self) -> Dict[str, Any]:
        assert self.store is not None
        return self.store.as_dict()

    def state_summary(self) -> List[Dict[str, Any]]:
        assert self.store is not None
        return self.store.summary()

    def events(self) -> List[Dict[str, Any]]:
        assert self.log is not None
        return self.log.as_dicts()

    def current_envelope(self) -> Dict[str, Any]:
        return self._envelope.to_dict() if self._envelope else {}

    def key_file(self) -> Dict[str, Any]:
        return dict(self._key_file)

    def report(self) -> Dict[str, Any]:
        """Final human-readable receipt once ValidationAgent has acted."""
        assert self.store is not None and self.log is not None
        verdict = self.store.get(KEY_VERDICT) if self.store.has(KEY_VERDICT) else None
        schema = self.store.get(KEY_SCHEMA) if self.store.has(KEY_SCHEMA) else None
        cleaned = self.store.get(KEY_CLEANED) if self.store.has(KEY_CLEANED) else None
        return {
            "run_id": self.run_id,
            "done": self.done,
            "verdict": verdict,
            "schema": schema,
            "cleaned_output": cleaned,
            "event_count": len(self.log.all()),
            "agents_acted": self._current,
            "total_agents": len(self._agents),
            "checks": (verdict or {}).get("checks", {}),
            "reasons": (verdict or {}).get("reasons", []),
        }

    def last_snapshot(self) -> Optional[StepSnapshot]:
        return self._last_snapshot