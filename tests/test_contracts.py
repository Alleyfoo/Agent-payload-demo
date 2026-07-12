"""Tests for the handoff envelope and contract validation."""

from __future__ import annotations

import pytest

from agent_network_demo.artifact_store import ArtifactStore
from agent_network_demo.contracts import (
    ACTION_READ_ARTIFACT,
    ACTION_WRITE_SCHEMA_PROFILE,
    ALLOWED_ACTIONS,
    ContractError,
    HandoffEnvelope,
    OUTPUT_CONTRACTS,
)


def make_env(**kw):
    base = dict(run_id="run_1", from_agent="a", to_agent="b",
                handoff_type="x")
    base.update(kw)
    return HandoffEnvelope(**base)


def test_validate_inbound_requires_input_keys_present():
    store = ArtifactStore()
    env = make_env(input_keys=["artifact.missing"])
    with pytest.raises(ContractError, match="missing"):
        env.validate_inbound(store)


def test_validate_inbound_passes_when_keys_present():
    store = ArtifactStore()
    store.register("artifact.x", {"type": "table_preview", "status": "ok"})
    env = make_env(input_keys=["artifact.x"], allowed_actions=[ACTION_READ_ARTIFACT])
    env.validate_inbound(store)  # no raise


def test_validate_inbound_requires_read_action_when_input_keys_present():
    store = ArtifactStore()
    store.register("artifact.x", {"type": "table_preview", "status": "ok"})
    # input_keys declared, but read_artifact not granted.
    env = make_env(input_keys=["artifact.x"], allowed_actions=[])
    with pytest.raises(ContractError, match="read_artifact"):
        env.validate_inbound(store)


def test_validate_inbound_requires_write_action_for_contract():
    store = ArtifactStore()
    # schema_profile contract, but write_schema_profile not granted.
    env = make_env(
        output_contract="schema_profile.v1",
        allowed_actions=[ACTION_READ_ARTIFACT],
    )
    with pytest.raises(ContractError, match="write_schema_profile"):
        env.validate_inbound(store)


def test_validate_inbound_table_preview_requires_write_action():
    store = ArtifactStore()
    env = make_env(
        output_contract="table_preview.v1",
        allowed_actions=[ACTION_READ_ARTIFACT],
    )
    with pytest.raises(ContractError, match="write_table_preview"):
        env.validate_inbound(store)


def test_validate_inbound_passes_when_actions_match_contract():
    store = ArtifactStore()
    store.register("artifact.x", {"type": "table_preview", "status": "ok"})
    env = make_env(
        input_keys=["artifact.x"],
        output_contract="schema_profile.v1",
        allowed_actions=[ACTION_READ_ARTIFACT, ACTION_WRITE_SCHEMA_PROFILE],
    )
    env.validate_inbound(store)  # no raise — grant matches obligation


def test_validate_inbound_rejects_unknown_action():
    store = ArtifactStore()
    env = make_env(allowed_actions=["hack_the_planet"])
    with pytest.raises(ContractError, match="unknown allowed_actions"):
        env.validate_inbound(store)


def test_validate_outbound_must_match_contract_prefix():
    env = make_env(output_contract="schema_profile.v1",
                   from_agent="schema_agent")
    env.validate_outbound(["artifact.schema_profile"])  # ok
    with pytest.raises(ContractError, match="does not match"):
        env.validate_outbound(["artifact.cleaned_output"])


def test_validate_outbound_rejects_writes_without_contract():
    env = make_env(output_contract="")
    with pytest.raises(ContractError, match="no output_contract"):
        env.validate_outbound(["artifact.x"])
    env.validate_outbound([])  # ok: declared nothing, wrote nothing


def test_validate_outbound_rejects_unknown_contract():
    env = make_env(output_contract="nope.v9")
    with pytest.raises(ContractError, match="unknown output_contract"):
        env.validate_outbound(["artifact.x"])


def test_action_vocabulary_is_closed():
    assert "read_artifact" in ALLOWED_ACTIONS
    assert "write_validation_verdict" in ALLOWED_ACTIONS
    assert "arbitrary_write" not in ALLOWED_ACTIONS


def test_output_contract_set_covers_all_agents():
    assert "table_preview.v1" in OUTPUT_CONTRACTS
    assert "schema_profile.v1" in OUTPUT_CONTRACTS
    assert "cleaned_output.v1" in OUTPUT_CONTRACTS
    assert "validation_verdict.v1" in OUTPUT_CONTRACTS


def test_envelope_to_dict_round_trips():
    env = make_env(input_keys=["a"], output_contract="schema_profile.v1",
                   context_summary="hi", allowed_actions=["read_artifact"])
    d = env.to_dict()
    assert d["input_keys"] == ["a"]
    assert d["output_contract"] == "schema_profile.v1"
    assert d["allowed_actions"] == ["read_artifact"]
