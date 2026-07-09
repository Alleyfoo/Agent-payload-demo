"""Tests for the deterministic mock agents: key-in / key-out behavior."""

from __future__ import annotations

import json

import pytest

from agent_network_demo.agents import (
    IntakeAgent,
    SchemaAgent,
    TransformAgent,
    ValidationAgent,
    KEY_CLEANED,
    KEY_RAW_INPUT,
    KEY_SCHEMA,
    KEY_VERDICT,
)
from agent_network_demo.artifact_store import ArtifactStore
from agent_network_demo.contracts import HandoffEnvelope, write_key_for
from agent_network_demo.event_log import EventLog

FIX_SAMPLE = "agent_network_demo/fixtures/sample_payload.json"
FIX_CSV = "agent_network_demo/fixtures/sample_payload.csv"


def seed_envelope(run_id="run_001", to_agent="intake_agent"):
    return HandoffEnvelope(
        run_id=run_id, from_agent="key_file", to_agent=to_agent,
        handoff_type="intake_request", input_keys=[],
        output_contract="table_preview.v1",
        context_summary="ingest_orders",
        allowed_actions=["read_artifact"],
    )


def _view(store, env):
    """Build the same capability-scoped view the runner hands an agent: read
    grant = the envelope's input_keys, write grant = its output_contract's
    key. Tests use this so they exercise the real capability path, not a
    permissive bare store."""
    return store.view(read_keys=list(env.input_keys),
                      write_key=write_key_for(env.output_contract))


def test_intake_writes_raw_preview(data_dir):
    store = ArtifactStore()
    log = EventLog("run_001", data_dir=str(data_dir))
    env = seed_envelope()
    out = IntakeAgent(source_ref=FIX_SAMPLE).run(env, _view(store, env), log)
    assert store.has(KEY_RAW_INPUT)
    art = store.get(KEY_RAW_INPUT)
    assert art["type"] == "table_preview"
    assert art["rows"] == 20
    assert art["columns"] == ["Order ID", "Customer", "Date", "Total"]
    assert out.to_agent == "schema_agent"
    assert out.input_keys == [KEY_RAW_INPUT]
    assert out.output_contract == "schema_profile.v1"
    events = log.all()
    assert len(events) == 1
    assert events[0].action == "write_artifact"
    assert events[0].output_keys == [KEY_RAW_INPUT]
    log.close()


def test_schema_infers_types(data_dir):
    store = ArtifactStore()
    log = EventLog("run_002", data_dir=str(data_dir))
    IntakeAgent(source_ref=FIX_SAMPLE).run(seed_envelope(), _view(store, seed_envelope()), log)
    env = HandoffEnvelope(run_id="run_002", from_agent="intake_agent",
                          to_agent="schema_agent", handoff_type="schema_request",
                          input_keys=[KEY_RAW_INPUT],
                          output_contract="schema_profile.v1")
    out = SchemaAgent().run(env, _view(store, env), log)
    assert store.has(KEY_SCHEMA)
    schema = store.get(KEY_SCHEMA)
    types = {f["name"]: f["type"] for f in schema["fields"]}
    assert types["Order ID"] == "integer"
    assert types["Customer"] == "string"
    assert types["Total"] == "float"
    assert out.to_agent == "transform_agent"
    log.close()


def test_transform_produces_cleaned_output(data_dir):
    store = ArtifactStore()
    log = EventLog("run_003", data_dir=str(data_dir))
    IntakeAgent(source_ref=FIX_SAMPLE).run(seed_envelope(), _view(store, seed_envelope()), log)
    env = HandoffEnvelope(run_id="run_003", from_agent="intake_agent",
                          to_agent="schema_agent", handoff_type="schema_request",
                          input_keys=[KEY_RAW_INPUT],
                          output_contract="schema_profile.v1")
    SchemaAgent().run(env, _view(store, env), log)
    env2 = HandoffEnvelope(run_id="run_003", from_agent="schema_agent",
                           to_agent="transform_agent",
                           handoff_type="transform_request",
                           input_keys=[KEY_RAW_INPUT, KEY_SCHEMA],
                           output_contract="cleaned_output.v1")
    out = TransformAgent().run(env2, _view(store, env2), log)
    assert store.has(KEY_CLEANED)
    cleaned = store.get(KEY_CLEANED)
    assert cleaned["row_count"] == 20
    assert cleaned["columns"] == ["Order ID", "Customer", "Date", "Total"]
    # integers stay integers, floats stay floats.
    first = cleaned["preview_rows"][0]
    assert first["Order ID"] == 1001
    assert isinstance(first["Total"], float)
    assert out.to_agent == "validation_agent"
    log.close()


def test_transform_coerces_string_numbers(data_dir, tmp_path):
    """A stringly-typed numeric value is coerced to the inferred type."""
    payload = {"rows": [
        {"Order ID": "1", "Customer": "X", "Date": "d", "Total": "9.5"},
        {"Order ID": "2", "Customer": "Y", "Date": "d", "Total": "10"},
    ]}
    src = tmp_path / "payload.json"
    src.write_text(json.dumps(payload), encoding="utf-8")

    store = ArtifactStore()
    log = EventLog("run_c", data_dir=str(data_dir))
    IntakeAgent(source_ref=str(src)).run(seed_envelope(), _view(store, seed_envelope()), log)
    env = HandoffEnvelope(run_id="run_c", from_agent="intake_agent",
                          to_agent="schema_agent", handoff_type="schema_request",
                          input_keys=[KEY_RAW_INPUT],
                          output_contract="schema_profile.v1")
    SchemaAgent().run(env, _view(store, env), log)
    env2 = HandoffEnvelope(run_id="run_c", from_agent="schema_agent",
                           to_agent="transform_agent",
                           handoff_type="transform_request",
                           input_keys=[KEY_RAW_INPUT, KEY_SCHEMA],
                           output_contract="cleaned_output.v1")
    TransformAgent().run(env2, _view(store, env2), log)
    cleaned = store.get(KEY_CLEANED)
    row = cleaned["preview_rows"][0]
    assert row["Order ID"] == 1
    assert isinstance(row["Order ID"], int)
    assert row["Total"] == 9.5
    assert isinstance(row["Total"], float)
    log.close()


def test_validation_writes_verdict_ok(data_dir):
    store = ArtifactStore()
    log = EventLog("run_004", data_dir=str(data_dir))
    # Walk the whole chain.
    IntakeAgent(source_ref=FIX_SAMPLE).run(seed_envelope(), _view(store, seed_envelope()), log)
    SchemaAgent().run(HandoffEnvelope(run_id="run_004", from_agent="intake_agent",
        to_agent="schema_agent", handoff_type="schema_request",
        input_keys=[KEY_RAW_INPUT], output_contract="schema_profile.v1"),
        store, log)
    TransformAgent().run(HandoffEnvelope(run_id="run_004",
        from_agent="schema_agent", to_agent="transform_agent",
        handoff_type="transform_request",
        input_keys=[KEY_RAW_INPUT, KEY_SCHEMA],
        output_contract="cleaned_output.v1"), store, log)
    env_v = HandoffEnvelope(run_id="run_004", from_agent="transform_agent",
        to_agent="validation_agent", handoff_type="validation_request",
        input_keys=[KEY_RAW_INPUT, KEY_SCHEMA, KEY_CLEANED],
        output_contract="validation_verdict.v1")
    out = ValidationAgent().run(env_v, _view(store, env_v), log)
    assert store.has(KEY_VERDICT)
    verdict = store.get(KEY_VERDICT)
    assert verdict["status"] == "ok"
    assert verdict["verdict"] == "ok"
    checks = verdict["checks"]
    assert checks["chain_complete"] is True
    assert checks["all_writes_allowed"] is True
    assert checks["schema_matches_output"] is True
    assert checks["row_counts_consistent"] is True
    assert out.to_agent == "human"
    log.close()


def test_validation_warns_on_incomplete_chain(data_dir):
    store = ArtifactStore()
    log = EventLog("run_005", data_dir=str(data_dir))
    # Only run intake — chain incomplete.
    IntakeAgent(source_ref=FIX_SAMPLE).run(seed_envelope(), _view(store, seed_envelope()), log)
    env_v = HandoffEnvelope(run_id="run_005", from_agent="transform_agent",
        to_agent="validation_agent", handoff_type="validation_request",
        input_keys=[], output_contract="validation_verdict.v1")
    ValidationAgent().run(env_v, _view(store, env_v), log)
    verdict = store.get(KEY_VERDICT)
    assert verdict["status"] == "warn"
    assert verdict["checks"]["chain_complete"] is False
    log.close()


def test_intake_reads_real_csv_and_transform_coerces(data_dir):
    """The shipped CSV is the real input: every cell arrives as a string, so
    the numeric columns are text here and TransformAgent coerces them into
    typed values. This is the visible transformation the UI shows."""
    store = ArtifactStore()
    log = EventLog("run_csv", data_dir=str(data_dir))
    IntakeAgent(source_ref=FIX_CSV).run(
        seed_envelope(), _view(store, seed_envelope()), log)
    raw = store.get(KEY_RAW_INPUT)
    # CSV values are all strings before coercion.
    assert raw["rows"] == 20
    first_raw = raw["preview_rows"][0]
    assert isinstance(first_raw["Order ID"], str)
    assert isinstance(first_raw["Total"], str)

    env = HandoffEnvelope(run_id="run_csv", from_agent="intake_agent",
                          to_agent="schema_agent", handoff_type="schema_request",
                          input_keys=[KEY_RAW_INPUT],
                          output_contract="schema_profile.v1")
    SchemaAgent().run(env, _view(store, env), log)
    env2 = HandoffEnvelope(run_id="run_csv", from_agent="schema_agent",
                           to_agent="transform_agent",
                           handoff_type="transform_request",
                           input_keys=[KEY_RAW_INPUT, KEY_SCHEMA],
                           output_contract="cleaned_output.v1")
    TransformAgent().run(env2, _view(store, env2), log)
    cleaned = store.get(KEY_CLEANED)
    assert cleaned["coerced_cells"] > 0
    first_clean = cleaned["preview_rows"][0]
    assert isinstance(first_clean["Order ID"], int)
    assert isinstance(first_clean["Total"], float)
    log.close()


def test_agents_do_not_carry_content_in_envelope(data_dir):
    """The core invariant: the outbound envelope carries only keys/refs,
    never artifact content."""
    store = ArtifactStore()
    log = EventLog("run_006", data_dir=str(data_dir))
    out = IntakeAgent(source_ref=FIX_SAMPLE).run(seed_envelope(), _view(store, seed_envelope()), log)
    # The envelope must not embed the table rows anywhere.
    blob = json.dumps(out.to_dict())
    assert "Alice Tan" not in blob
    assert "42.5" not in blob
    log.close()