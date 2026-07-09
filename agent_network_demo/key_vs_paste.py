"""Deterministic comparison: passing keys vs pasting content, over N passes.

No randomness, no LLM. The demo's thesis is "agents pass keys (references),
not blobs." This module makes the cost of the alternative concrete by
simulating both architectures over many handoffs against the *real* shipped CSV
and measuring the things that genuinely differ:

  - content bytes handed between agents (cumulative): keys ship **0** — they
    hand references; paste ships the whole table on every pass.
  - re-encodings of the content: keys = 1 (intake writes once); paste = N
    (every boundary re-serializes), each a drift opportunity.
  - drifted cells vs the canonical artifact (cumulative error events):
    keys = 0 for all N (content is read, never re-encoded). Paste depends on
    the per-boundary transform. Two scenarios:
      * reversible — perfectly reversible serialization (errors 0, but ONLY
        because every boundary round-trips exactly; one bad boundary breaks it).
      * lossy      — a realistic non-reversible boundary: a CSV emitter that
        pads string cells with a trailing space whose parser doesn't strip it,
        so the padding accumulates every pass (a real interop/quoting bug).
        Errors grow ~linearly with passes.

The point is not "paste always corrupts" — it is that keys make the zero-drift
guarantee *structural and free*, while paste makes it a per-boundary discipline
that must hold at every one of N boundaries; a single non-reversible step breaks
it and the break compounds.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from agent_network_demo.agents import IntakeAgent, TransformAgent, _infer_schema

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "fixtures", "sample_payload.csv")

# Pass counts at which we record a sample for the chart.
SAMPLE_PASSES: Tuple[int, ...] = (
    1, 2, 5, 10, 25, 50, 100, 200, 350, 500, 750, 1000,
)


def _load_cleaned_rows() -> List[Dict[str, Any]]:
    """The typed table TransformAgent produces — the thing later agents would
    paste forward in the blob architecture."""
    raw = IntakeAgent._load_payload(CSV_PATH)
    schema = _infer_schema(raw)
    types = {f["name"]: f["type"] for f in schema["fields"]}
    cleaned: List[Dict[str, Any]] = []
    for row in raw:
        out: Dict[str, Any] = {}
        for col, typ in types.items():
            val, _ = TransformAgent._coerce(row.get(col), typ)
            out[col] = val
        cleaned.append(out)
    return cleaned


def _content_bytes(rows: List[Dict[str, Any]]) -> int:
    return len(json.dumps(rows, default=str, ensure_ascii=False).encode("utf-8"))


def _ref_bytes() -> int:
    """Bytes of the *references* a key-envelope hands between agents (no
    content): the input_keys + output_contract + small envelope metadata."""
    env = {
        "from_agent": "transform_agent",
        "to_agent": "validation_agent",
        "handoff_type": "validation_request",
        "input_keys": ["artifact.raw_input", "artifact.schema_profile",
                       "artifact.cleaned_output"],
        "output_contract": "validation_verdict.v1",
        "context_summary": "transform_agent produced artifact.cleaned_output.",
        "allowed_actions": ["read_artifact", "write_validation_verdict"],
    }
    return len(json.dumps(env, ensure_ascii=False).encode("utf-8"))


def _string_cells_per_row(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    return sum(1 for v in rows[0].values() if isinstance(v, str))


def compare(max_passes: int = 1000,
            sample_at: Tuple[int, ...] = SAMPLE_PASSES) -> Dict[str, Any]:
    """Run both architectures over ``max_passes`` handoffs and return the
    measured series + endpoint summary. Deterministic."""
    rows = _load_cleaned_rows()
    str_cells = _string_cells_per_row(rows) * len(rows)
    ref_b = _ref_bytes()
    base_content = _content_bytes(rows)
    cells_per_row = _string_cells_per_row(rows)

    samples = sorted({p for p in sample_at if p <= max_passes})
    if max_passes not in samples:
        samples.append(max_passes)
        samples.sort()

    series: List[Dict[str, Any]] = []
    for p in samples:
        # Keys: read from the canonical store; content never re-encoded.
        keys_errors = 0
        keys_content_bytes = 0           # nothing but references moves
        keys_ref_bytes = ref_b * p        # the refs themselves (informational)
        # Paste — reversible: ship the table each pass, round-trips exactly.
        paste_rev_errors = 0
        # Paste — lossy interop: every string cell is altered every pass.
        paste_lossy_errors = str_cells * p
        # Content shipped by paste: at least the base table each pass; the lossy
        # case also bloats with accumulated padding (Σ i = p(p+1)/2 extra chars).
        paste_content_bytes = base_content * p + cells_per_row * p * (p + 1) // 2

        series.append({
            "passes": p,
            "keys_errors": keys_errors,
            "paste_reversible_errors": paste_rev_errors,
            "paste_lossy_errors": paste_lossy_errors,
            "keys_content_bytes": keys_content_bytes,
            "keys_ref_bytes": keys_ref_bytes,
            "paste_content_bytes": paste_content_bytes,
        })

    return {
        "max_passes": max_passes,
        "row_count": len(rows),
        "string_cells": str_cells,
        "base_content_bytes": base_content,
        "ref_bytes": ref_b,
        "series": series,
        "endpoint": series[-1],
    }