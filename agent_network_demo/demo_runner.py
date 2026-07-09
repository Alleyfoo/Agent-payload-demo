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
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Ensure the package parent (repo root) is on sys.path so the absolute imports
# below resolve whether this module is run as a script (e.g. as the Streamlit
# entrypoint), imported as a top-level module, or imported as part of the
# agent_network_demo package. On Streamlit Cloud only the script's own
# directory is placed on sys.path, so without this `agent_network_demo` is not
# importable.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_network_demo.agents import (
    IntakeAgent,
    SchemaAgent,
    TransformAgent,
    ValidationAgent,
    KEY_CLEANED,
    KEY_RAW_INPUT,
    KEY_SCHEMA,
    KEY_VERDICT,
    confine_path,
)
from agent_network_demo.artifact_store import ArtifactStore
from agent_network_demo.contracts import HandoffEnvelope, ContractError, write_key_for
from agent_network_demo.event_log import Event, EventLog


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
        ordered agent list, set the seed envelope, and return the run id.

        ``key_file_path`` is opened directly — the public UI only ever hands
        the runner a key file chosen from the bundled fixtures, so the path is
        trusted. The key file's ``source_ref`` (the payload path) is untrusted
        *data*, so it is confined to the fixtures dir here before any agent
        opens it: a key file cannot point the demo at an arbitrary file."""
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

        # Confine the payload path to the fixtures dir — defense against a
        # key file that points outside the demo's data.
        source_ref = confine_path(
            self._key_file.get("source_ref", "sample_payload.json")
        )
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
        try:
            # Inbound contract check: declared input keys must exist.
            envelope.validate_inbound(self.store)

            # Hand the agent a *capability-scoped* view of the store, not the
            # store itself. The envelope's input_keys are the read grant; the
            # output_contract's key is the single write grant. The view raises
            # ContractError on any read/write outside those grants — that is
            # what makes "passing keys" load-bearing instead of decorative.
            view = self.store.view(
                read_keys=list(envelope.input_keys),
                write_key=write_key_for(envelope.output_contract),
            )
            # Snapshot the store before the agent runs so we can check, after
            # it returns, exactly which keys it wrote this step. The scoped
            # view already blocks any write outside the contracted key; this
            # outbound check is the second half the runner's docstring promises
            # ("validates each envelope inbound and outbound") and it also
            # catches a write that bypasses the view entirely (e.g. a future
            # agent handed the raw store) — the keys newly in the store must
            # all match the inbound envelope's declared output_contract.
            keys_before = set(self.store.keys())
            new_envelope = agent.run(envelope, view, self.log)
            new_keys = sorted(set(self.store.keys()) - keys_before)
            envelope.validate_outbound(new_keys)

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

    def log_path(self) -> str:
        """Path to the on-disk JSONL logfile for this run (empty if no run)."""
        return self.log.path if self.log is not None else ""

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