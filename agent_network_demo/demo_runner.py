"""Trusted workflow runner for the deterministic agent payload demo."""

from __future__ import annotations

import json
import os
import sys
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_network_demo.agents import (
    IntakeAgent, SchemaAgent, TransformAgent, ValidationAgent,
    KEY_CLEANED, KEY_RAW_INPUT, KEY_SCHEMA, KEY_VERDICT, confine_path,
)
from agent_network_demo.artifact_store import ArtifactStore
from agent_network_demo.contracts import (
    ACTION_READ_ARTIFACT, ACTION_WRITE_CLEANED_OUTPUT,
    ACTION_WRITE_SCHEMA_PROFILE, ACTION_WRITE_TABLE_PREVIEW,
    ACTION_WRITE_VALIDATION_VERDICT, CONTRACT_CLEANED_OUTPUT,
    CONTRACT_SCHEMA_PROFILE, CONTRACT_TABLE_PREVIEW,
    CONTRACT_VALIDATION_VERDICT, ContractError, HandoffEnvelope, write_key_for,
)
from agent_network_demo.event_log import Event, EventLog


@dataclass(frozen=True)
class Route:
    agent: str
    handoff_type: str
    input_keys: Tuple[str, ...]
    output_contract: str
    allowed_actions: Tuple[str, ...]
    next_stage: Optional[str]


WORKFLOW_ROUTES: Dict[str, Route] = {
    "intake": Route("intake_agent", "intake_request", (), CONTRACT_TABLE_PREVIEW,
                    (ACTION_WRITE_TABLE_PREVIEW,), "schema"),
    "schema": Route("schema_agent", "schema_request", (KEY_RAW_INPUT,),
                    CONTRACT_SCHEMA_PROFILE,
                    (ACTION_READ_ARTIFACT, ACTION_WRITE_SCHEMA_PROFILE), "transform"),
    "transform": Route("transform_agent", "transform_request",
                       (KEY_RAW_INPUT, KEY_SCHEMA), CONTRACT_CLEANED_OUTPUT,
                       (ACTION_READ_ARTIFACT, ACTION_WRITE_CLEANED_OUTPUT), "validation"),
    "validation": Route("validation_agent", "validation_request",
                        (KEY_RAW_INPUT, KEY_SCHEMA, KEY_CLEANED),
                        CONTRACT_VALIDATION_VERDICT,
                        (ACTION_READ_ARTIFACT, ACTION_WRITE_VALIDATION_VERDICT), None),
}


@dataclass
class StepSnapshot:
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
    AGENT_NAMES = tuple(route.agent for route in WORKFLOW_ROUTES.values())

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.run_id = ""
        self.store: Optional[ArtifactStore] = None
        self.log: Optional[EventLog] = None
        self._agents: List[Any] = []
        self._stages = list(WORKFLOW_ROUTES)
        self._current = 0
        self._envelope: Optional[HandoffEnvelope] = None
        self._key_file: Dict[str, Any] = {}
        self._receipts: List[Dict[str, Any]] = []
        self._last_snapshot: Optional[StepSnapshot] = None
        self.done = False
        self.error: Optional[str] = None

    def _envelope_for(self, stage: str, from_agent: str, summary: str) -> HandoffEnvelope:
        route = WORKFLOW_ROUTES[stage]
        return HandoffEnvelope(
            run_id=self.run_id, from_agent=from_agent, to_agent=route.agent,
            handoff_type=route.handoff_type, input_keys=list(route.input_keys),
            output_contract=route.output_contract, context_summary=summary,
            allowed_actions=list(route.allowed_actions),
        )

    def start_run(self, key_file_path: str = "fixtures/key_file.json") -> str:
        if not os.path.exists(key_file_path):
            raise FileNotFoundError(f"key file not found: {key_file_path}")
        with open(key_file_path, "r", encoding="utf-8") as fh:
            self._key_file = json.load(fh)

        self.run_id = f"run_{uuid.uuid4().hex}"
        self.store = ArtifactStore()
        self.log = EventLog(self.run_id, data_dir=self.data_dir)
        source_ref = confine_path(self._key_file.get("source_ref", "sample_payload.json"))
        self._receipts = []
        self._agents = [
            IntakeAgent(source_ref=source_ref), SchemaAgent(), TransformAgent(),
            ValidationAgent(self._receipts),
        ]
        self._current = 0
        self.done = False
        self.error = None
        # Key-file actions are intentionally ignored; runtime grants come only
        # from WORKFLOW_ROUTES.
        self._envelope = self._envelope_for(
            "intake", "key_file", self._key_file.get("run_intent", "ingest_orders")
        )
        self._last_snapshot = None
        return self.run_id

    def step(self) -> StepSnapshot:
        if self.done:
            raise RuntimeError("run is complete; call reset() to start again")
        if self._current >= len(self._agents):
            self.done = True
            raise RuntimeError("no agent left to run")

        assert self.store is not None and self.log is not None and self._envelope
        agent = self._agents[self._current]
        envelope = self._envelope
        route = WORKFLOW_ROUTES[self._stages[self._current]]
        status, message, contract_result = "ok", "", "passed"
        event_count_before = len(self.log.all())
        keys_before = set(self.store.keys())
        view = self.store.view(list(envelope.input_keys), write_key_for(envelope.output_contract))

        try:
            envelope.validate_inbound(self.store)
            result = agent.run(envelope, view, self.log)
            new_keys = sorted(set(self.store.keys()) - keys_before)
            envelope.validate_outbound(new_keys)
            granted_output = write_key_for(envelope.output_contract)
            if new_keys != [granted_output]:
                raise ContractError(
                    f"actual writes {new_keys} != granted output {[granted_output]}"
                )
            if not set(view.read_keys).issubset(envelope.input_keys):
                raise ContractError("actual reads exceeded the runner grant")
            declared = getattr(result, "output_keys", new_keys)
            if sorted(declared) != new_keys:
                raise ContractError(f"agent result output keys {declared} != actual {new_keys}")
            summary = getattr(result, "summary", f"{agent.name} completed")
            self._current += 1
            if route.next_stage is None:
                self.done = True
                self._envelope = HandoffEnvelope(
                    self.run_id, route.agent, "human", "report", [KEY_VERDICT],
                    "", summary, [],
                )
            else:
                self._envelope = self._envelope_for(route.next_stage, route.agent, summary)
        except ContractError as exc:
            status, contract_result = "error", "failed"
            message = f"contract violation: {exc}"
            self.error = message
            self._emit_error(agent.name, str(exc))
        except Exception as exc:  # noqa: BLE001
            status, contract_result = "error", "failed"
            message = f"{type(exc).__name__}: {exc}"
            self.error = message
            self._emit_error(agent.name, message)

        actual_new_keys = sorted(set(self.store.keys()) - keys_before)
        receipt = {
            "agent": agent.name,
            "granted_input_keys": list(envelope.input_keys),
            "granted_output_key": write_key_for(envelope.output_contract),
            "keys_actually_read": view.read_keys,
            "keys_actually_written": actual_new_keys,
            "contract_result": contract_result,
            "status": status,
        }
        self._receipts.append(receipt)
        self.log.append(Event(
            run_id=self.run_id, agent="trusted_runner", action="step_receipt",
            input_keys=receipt["keys_actually_read"],
            output_keys=receipt["keys_actually_written"], status=status,
            checks=deepcopy(receipt), message=f"Receipt for {agent.name}: {contract_result}.",
        ))

        new_events = [e.to_dict() for e in self.log.all()[event_count_before:]]
        snap = StepSnapshot(
            self.run_id, self._current, agent.name, self.chain_status(),
            self._envelope.to_dict() if self._envelope else {}, self.store.keys(),
            new_events, status, message or f"{agent.name} ran.", self.done,
        )
        self._last_snapshot = snap
        return snap

    def _emit_error(self, agent_name: str, message: str) -> None:
        assert self.log is not None
        self.log.append(Event(self.run_id, agent_name, "error", [], [], "error", {}, message))

    def reset(self) -> None:
        if self.log is not None:
            self.log.close()
        self.__init__(self.data_dir)

    def chain_status(self) -> List[Dict[str, str]]:
        return [{"agent": name,
                 "state": "acted" if i < self._current else
                          "control" if i == self._current and not self.done else "waiting"}
                for i, name in enumerate(self.AGENT_NAMES)]

    def state(self) -> Dict[str, Any]:
        assert self.store is not None
        return self.store.as_dict()

    def state_summary(self) -> List[Dict[str, Any]]:
        assert self.store is not None
        return self.store.summary()

    def events(self) -> List[Dict[str, Any]]:
        assert self.log is not None
        return self.log.as_dicts()

    def receipts(self) -> List[Dict[str, Any]]:
        return deepcopy(self._receipts)

    def log_path(self) -> str:
        return self.log.path if self.log is not None else ""

    def current_envelope(self) -> Dict[str, Any]:
        return self._envelope.to_dict() if self._envelope else {}

    def key_file(self) -> Dict[str, Any]:
        return deepcopy(self._key_file)

    def report(self) -> Dict[str, Any]:
        assert self.store is not None and self.log is not None
        verdict = self.store.get(KEY_VERDICT) if self.store.has(KEY_VERDICT) else None
        schema = self.store.get(KEY_SCHEMA) if self.store.has(KEY_SCHEMA) else None
        cleaned = self.store.get(KEY_CLEANED) if self.store.has(KEY_CLEANED) else None
        return {"run_id": self.run_id, "done": self.done, "verdict": verdict,
                "schema": schema, "cleaned_output": cleaned,
                "event_count": len(self.log.all()), "agents_acted": self._current,
                "total_agents": len(self._agents), "receipts": self.receipts(),
                "checks": (verdict or {}).get("checks", {}),
                "reasons": (verdict or {}).get("reasons", [])}

    def last_snapshot(self) -> Optional[StepSnapshot]:
        return self._last_snapshot
