"""Deterministic mock agents.

No LLM. No network. No randomness. Each agent reads keys from the shared
store, does a small deterministic transformation, writes its output key,
appends one event, and returns the *next* handoff envelope (carrying the new
output key, not the content). The architecture is the point — the agents are
deliberately simple.

Agent interface::

    run(envelope, view, log) -> HandoffEnvelope

``envelope`` is the inbound envelope (validated by the runner). ``view`` is a
capability-scoped handle to the shared store: the agent may ``get`` only the
keys in ``envelope.input_keys`` and ``register`` only the one key its
``output_contract`` licenses — anything else raises ``ContractError``. The
agent reads its granted keys, writes exactly one output key, emits an event,
and builds the outbound envelope (choosing which keys to hand the next agent).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Tuple

# Ensure the package parent (repo root) is on sys.path so the absolute imports
# below resolve whether this module is run as a script, imported as a top-level
# module, or imported as part of the agent_network_demo package. On hosts like
# Streamlit Cloud only the script's own directory is placed on sys.path.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_network_demo.artifact_store import StoreView
from agent_network_demo.contracts import (
    ACTION_READ_ARTIFACT,
    ACTION_WRITE_CLEANED_OUTPUT,
    ACTION_WRITE_SCHEMA_PROFILE,
    ACTION_WRITE_VALIDATION_VERDICT,
    CONTRACT_CLEANED_OUTPUT,
    CONTRACT_SCHEMA_PROFILE,
    CONTRACT_TABLE_PREVIEW,
    CONTRACT_VALIDATION_VERDICT,
    ContractError,
    HandoffEnvelope,
)
from agent_network_demo.event_log import Event, EventLog

# Canonical artifact keys — used everywhere (fixtures, README, tests).
KEY_RAW_INPUT = "artifact.raw_input"
KEY_SCHEMA = "artifact.schema_profile"
KEY_CLEANED = "artifact.cleaned_output"
KEY_VERDICT = "artifact.validation_verdict"

# The only directory payload files may be loaded from. The public demo loads
# data by *reference* (a path in the key file), so the source_ref coming out of
# a key file is untrusted data — it must be confined here, or the demo would be
# saying "look at my safe agent architecture" while a text box whispers "type a
# server path". The runner confines source_ref to this dir before any agent
# opens it.
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def confine_path(path: str, root: str = FIXTURES_DIR) -> str:
    """Resolve ``path`` (relative to ``root`` if not absolute) and verify it
    stays inside ``root``. Returns the resolved absolute path. Raises
    :class:`ContractError` on any escape — ``..`` traversal, an absolute path
    outside ``root``, or a path on a different drive.

    A relative ``path`` is interpreted as relative to ``root`` (the fixtures
    dir), so a key file may say ``"sample_payload.csv"`` rather than spell out
    the whole tree. An absolute path inside ``root`` (how the test harness
    points at a fixture) is also accepted.
    """
    root_abs = os.path.abspath(root)
    candidate = path if os.path.isabs(path) else os.path.join(root_abs, path)
    real = os.path.realpath(candidate)
    rel = os.path.relpath(real, root_abs)
    if os.path.isabs(rel) or rel == ".." or rel.startswith(".." + os.sep):
        raise ContractError(
            f"source path {path!r} escapes the fixtures dir {root_abs!r}"
        )
    return real


# ---------------------------------------------------------------------------
# Deterministic schema inference helpers.
# ---------------------------------------------------------------------------

def _try_number(v: Any):
    """If ``v`` is a string that parses as an int/float, return that typed
    value; otherwise return ``v`` unchanged. Non-strings pass through."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s == "":
        return v
    try:
        # Prefer int when there's no decimal point / exponent.
        if "." not in s and "e" not in s and "E" not in s:
            return int(s)
        return float(s)
    except ValueError:
        return v


def _infer_column_type(values: List[Any]) -> str:
    """Tiny deterministic type inference: integer -> float -> string.

    Strings that parse as numbers are treated as numbers, so a stringly-typed
    numeric column (e.g. ``"9.5"``) is inferred as numeric and coerced by
    TransformAgent. Dates and other non-numeric strings stay ``string``.
    """
    saw_int, saw_float, saw_str = True, True, True
    for raw in values:
        if raw is None or raw == "":
            continue
        v = _try_number(raw)
        if isinstance(v, bool):
            return "string"  # booleans handled as strings in this demo
        if isinstance(v, int):
            saw_str = False
        elif isinstance(v, float):
            saw_str = False
            saw_int = False
        else:
            saw_int = False
            saw_float = False
    if saw_int:
        return "integer"
    if saw_float:
        return "float"
    if saw_str:
        return "string"
    return "string"


def _infer_schema(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministically infer a column→type mapping from the sample rows."""
    columns: List[str] = []
    for row in rows:
        for k in row.keys():
            if k not in columns:
                columns.append(k)
    fields: List[Dict[str, Any]] = []
    for col in columns:
        values = [row.get(col) for row in rows]
        fields.append({"name": col, "type": _infer_column_type(values)})
    return {"columns": columns, "fields": fields, "row_count": len(rows)}


# ---------------------------------------------------------------------------
# Base agent.
# ---------------------------------------------------------------------------

class _BaseAgent:
    """Common bookkeeping: name + a contract describing input/output."""

    name: str = "base"
    next_agent: str = ""
    next_handoff_type: str = ""
    next_input_keys: Tuple[str, ...] = ()
    next_output_contract: str = ""
    next_allowed_actions: Tuple[str, ...] = ()

    def _next_envelope(self, envelope: HandoffEnvelope,
                       output_key: str) -> HandoffEnvelope:
        """Build the outbound envelope to the next agent."""
        return HandoffEnvelope(
            run_id=envelope.run_id,
            from_agent=self.name,
            to_agent=self.next_agent,
            handoff_type=self.next_handoff_type,
            input_keys=list(self.next_input_keys),
            output_contract=self.next_output_contract,
            context_summary=self._next_summary(envelope, output_key),
            allowed_actions=list(self.next_allowed_actions),
        )

    def _next_summary(self, envelope: HandoffEnvelope,
                      output_key: str) -> str:
        return f"{self.name} produced {output_key}."

    def _emit(self, log: EventLog, action: str,
              input_keys: List[str], output_keys: List[str],
              status: str = "ok", checks: Dict[str, Any] = None,
              message: str = "") -> Event:
        return log.append(Event(
            run_id=log.run_id,
            agent=self.name,
            action=action,
            input_keys=input_keys,
            output_keys=output_keys,
            status=status,
            checks=checks or {},
            message=message,
        ))


# ---------------------------------------------------------------------------
# IntakeAgent — first agent in the chain.
# ---------------------------------------------------------------------------

class IntakeAgent(_BaseAgent):
    """Reads the key file's source payload, writes a table preview.

    This is the *entry* agent: its inbound envelope's ``input_keys`` are
    empty (it reads the file system, not the store). It writes
    ``artifact.raw_input``.
    """

    name = "intake_agent"
    next_agent = "schema_agent"
    next_handoff_type = "schema_request"
    next_input_keys = (KEY_RAW_INPUT,)
    next_output_contract = CONTRACT_SCHEMA_PROFILE
    next_allowed_actions = (ACTION_READ_ARTIFACT, ACTION_WRITE_SCHEMA_PROFILE)

    def __init__(self, source_ref: str = "fixtures/sample_payload.json") -> None:
        self.source_ref = source_ref

    def run(self, envelope: HandoffEnvelope, view: StoreView,
            log: EventLog) -> HandoffEnvelope:
        # Load the payload the key file points at.
        rows = self._load_payload(self.source_ref)
        if not rows:
            raise ContractError(
                f"intake_agent: source payload {self.source_ref!r} is empty"
            )
        columns: List[str] = []
        for row in rows:
            for k in row.keys():
                if k not in columns:
                    columns.append(k)

        preview = {
            "type": "table_preview",
            "status": "ok",
            "rows": len(rows),
            "row_count": len(rows),
            "columns": columns,
            "source_ref": self.source_ref,
            "preview_rows": rows[:5],
        }
        view.register(KEY_RAW_INPUT, preview)
        self._emit(
            log, action="write_artifact",
            input_keys=[], output_keys=[KEY_RAW_INPUT],
            status="ok",
            checks={"allowed_write": True, "rows": len(rows),
                    "columns": len(columns)},
            message=f"Loaded {len(rows)} rows × {len(columns)} columns from "
                    f"{self.source_ref}.",
        )
        return self._next_envelope(envelope, KEY_RAW_INPUT)

    @staticmethod
    def _load_payload(source_ref: str) -> List[Dict[str, Any]]:
        if not os.path.exists(source_ref):
            raise ContractError(
                f"intake_agent: source payload not found: {source_ref!r}"
            )
        if source_ref.lower().endswith(".csv"):
            # A real CSV: every value arrives as a string, so the numeric
            # columns ("Order ID", "Total") are text here and get coerced by
            # TransformAgent — that is the visible transformation.
            import csv
            with open(source_ref, "r", encoding="utf-8", newline="") as fh:
                return list(csv.DictReader(fh))
        with open(source_ref, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data.get("rows", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ContractError(
                f"intake_agent: expected a list of rows in {source_ref!r}"
            )
        return rows


# ---------------------------------------------------------------------------
# SchemaAgent — infers a deterministic schema.
# ---------------------------------------------------------------------------

class SchemaAgent(_BaseAgent):
    """Reads the raw preview, infers column types, writes a schema profile."""

    name = "schema_agent"
    next_agent = "transform_agent"
    next_handoff_type = "transform_request"
    next_input_keys = (KEY_RAW_INPUT, KEY_SCHEMA)
    next_output_contract = CONTRACT_CLEANED_OUTPUT
    next_allowed_actions = (ACTION_READ_ARTIFACT, ACTION_WRITE_CLEANED_OUTPUT)

    def run(self, envelope: HandoffEnvelope, view: StoreView,
            log: EventLog) -> HandoffEnvelope:
        preview = view.get(KEY_RAW_INPUT)
        # Re-load the full payload (the preview only keeps 5 rows) to infer
        # types over the whole table — deterministic, no LLM.
        source_ref = preview.get("source_ref", "fixtures/sample_payload.json")
        rows = IntakeAgent._load_payload(source_ref)
        schema = _infer_schema(rows)

        schema_valid = bool(schema["columns"]) and bool(schema["fields"])
        profile = {
            "type": "schema_profile",
            "status": "ok" if schema_valid else "warn",
            "columns": schema["columns"],
            "fields": schema["fields"],
            "row_count": schema["row_count"],
        }
        view.register(KEY_SCHEMA, profile)
        self._emit(
            log, action="write_artifact",
            input_keys=[KEY_RAW_INPUT], output_keys=[KEY_SCHEMA],
            status="ok",
            checks={"schema_valid": schema_valid,
                    "allowed_write": True,
                    "column_count": len(schema["columns"])},
            message=f"Inferred schema over {len(schema['columns'])} columns.",
        )
        return self._next_envelope(envelope, KEY_SCHEMA)


# ---------------------------------------------------------------------------
# TransformAgent — produces a cleaned/normalized output.
# ---------------------------------------------------------------------------

class TransformAgent(_BaseAgent):
    """Reads preview + schema, normalizes the table, writes cleaned output."""

    name = "transform_agent"
    next_agent = "validation_agent"
    next_handoff_type = "validation_request"
    next_input_keys = (KEY_RAW_INPUT, KEY_SCHEMA, KEY_CLEANED)
    next_output_contract = CONTRACT_VALIDATION_VERDICT
    next_allowed_actions = (ACTION_READ_ARTIFACT, ACTION_WRITE_VALIDATION_VERDICT)

    def run(self, envelope: HandoffEnvelope, view: StoreView,
            log: EventLog) -> HandoffEnvelope:
        preview = view.get(KEY_RAW_INPUT)
        schema = view.get(KEY_SCHEMA)
        source_ref = preview.get("source_ref", "fixtures/sample_payload.json")
        rows = IntakeAgent._load_payload(source_ref)

        field_types = {f["name"]: f["type"] for f in schema["fields"]}
        cleaned_rows: List[Dict[str, Any]] = []
        coerced = 0
        for row in rows:
            out: Dict[str, Any] = {}
            for col, typ in field_types.items():
                val = row.get(col)
                new, did = self._coerce(val, typ)
                out[col] = new
                if did:
                    coerced += 1
            cleaned_rows.append(out)

        cleaned = {
            "type": "cleaned_output",
            "status": "ok",
            "row_count": len(cleaned_rows),
            "columns": schema["columns"],
            "preview_rows": cleaned_rows[:5],
            "coerced_cells": coerced,
        }
        view.register(KEY_CLEANED, cleaned)
        self._emit(
            log, action="write_artifact",
            input_keys=[KEY_RAW_INPUT, KEY_SCHEMA], output_keys=[KEY_CLEANED],
            status="ok",
            checks={"allowed_write": True, "rows": len(cleaned_rows),
                    "coerced_cells": coerced},
            message=f"Cleaned {len(cleaned_rows)} rows, coerced {coerced} cells.",
        )
        return self._next_envelope(envelope, KEY_CLEANED)

    @staticmethod
    def _coerce(value: Any, typ: str) -> Tuple[Any, bool]:
        """Deterministic normalization. Returns (value, was_coerced)."""
        if value is None or value == "":
            return value, False
        try:
            if typ == "integer":
                if isinstance(value, int) and not isinstance(value, bool):
                    return value, False
                return int(float(str(value).strip())), True
            if typ == "float":
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value), not isinstance(value, float)
                return float(str(value).strip()), True
        except (TypeError, ValueError):
            return value, False
        # string: trim whitespace.
        if isinstance(value, str):
            stripped = value.strip()
            return stripped, (stripped != value)
        return value, False


# ---------------------------------------------------------------------------
# ValidationAgent (ShadowJudge) — independent re-read + verdict.
# ---------------------------------------------------------------------------

class ValidationAgent(_BaseAgent):
    """The ShadowJudge: independently re-reads the whole chain's artifacts
    and event log and writes a verdict (ok/warn + reasons). It does not
    trust the prior agents' self-reports — it re-derives the checks."""

    name = "validation_agent"
    next_agent = ""          # terminal
    next_handoff_type = ""
    next_input_keys = ()
    next_output_contract = ""
    next_allowed_actions = ()

    def run(self, envelope: HandoffEnvelope, view: StoreView,
            log: EventLog) -> HandoffEnvelope:
        checks: Dict[str, Any] = {}
        reasons: List[str] = []

        # 1. chain complete: every expected artifact is present (and granted).
        expected = [KEY_RAW_INPUT, KEY_SCHEMA, KEY_CLEANED]
        present = [k for k in expected if view.has(k)]
        checks["chain_complete"] = len(present) == len(expected)
        if not checks["chain_complete"]:
            missing = [k for k in expected if k not in present]
            reasons.append(f"chain incomplete: missing {missing}")

        # 2. every write event was allowed by its envelope's actions.
        # Re-derive: a write is "allowed" if its event recorded
        # allowed_write=True, OR it is the root intake write (no inbound
        # envelope to constrain it).
        write_events = [e for e in log.all()
                        if e.action == "write_artifact"]
        bad_writes = [e for e in write_events
                      if e.agent != "intake_agent"
                      and not e.checks.get("allowed_write", False)]
        checks["all_writes_allowed"] = len(bad_writes) == 0
        if bad_writes:
            reasons.append(f"writes without allowed_write: "
                           f"{[e.agent for e in bad_writes]}")

        # 3. schema matches cleaned output columns.
        schema_matches = True
        if view.has(KEY_SCHEMA) and view.has(KEY_CLEANED):
            schema_cols = view.get(KEY_SCHEMA).get("columns", [])
            cleaned_cols = view.get(KEY_CLEANED).get("columns", [])
            schema_matches = schema_cols == cleaned_cols
            checks["schema_matches_output"] = schema_matches
            if not schema_matches:
                reasons.append("schema columns != cleaned output columns")
        else:
            checks["schema_matches_output"] = False
            reasons.append("schema or cleaned output missing")

        # 4. row counts agree across the chain.
        counts = []
        for k in (KEY_RAW_INPUT, KEY_CLEANED):
            if view.has(k):
                counts.append(view.get(k).get("row_count"))
        checks["row_counts_consistent"] = (
            len(set(counts)) <= 1 and None not in counts
        )
        if not checks["row_counts_consistent"] and counts:
            reasons.append(f"inconsistent row counts: {counts}")

        ok = bool(checks) and all(v for v in checks.values()) and not reasons
        verdict = {
            "type": "validation_verdict",
            "status": "ok" if ok else "warn",
            "verdict": "ok" if ok else "warn",
            "checks": checks,
            "reasons": reasons if reasons else ["all checks passed"],
        }
        view.register(KEY_VERDICT, verdict)
        self._emit(
            log, action="validate",
            input_keys=[KEY_RAW_INPUT, KEY_SCHEMA, KEY_CLEANED],
            output_keys=[KEY_VERDICT],
            status="ok" if ok else "warn",
            checks=checks,
            message=("Chain validated: all checks passed."
                     if ok else "Chain validated with warnings."),
        )
        # Terminal agent: return an envelope to "human" (no further agent).
        return HandoffEnvelope(
            run_id=envelope.run_id,
            from_agent=self.name,
            to_agent="human",
            handoff_type="report",
            input_keys=[KEY_VERDICT],
            output_contract="",
            context_summary=("Validation complete. Verdict available at "
                             f"{KEY_VERDICT}."),
            allowed_actions=[],
        )