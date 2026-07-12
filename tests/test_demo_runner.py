"""Tests for the RunSession: stepping the chain end-to-end."""

from __future__ import annotations

import json

import pytest

from agent_network_demo.agents import IntakeAgent
from agent_network_demo.contracts import HandoffEnvelope
from agent_network_demo.demo_runner import RunSession
from agent_network_demo.event_log import Event


def test_start_run_seeds_envelope(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    rid = sess.start_run(key_file_path)
    assert rid.startswith("run_")
    env = sess.current_envelope()
    assert env["to_agent"] == "intake_agent"
    assert sess.chain_status()[0]["state"] == "control"
    assert all(n["state"] == "waiting" for n in sess.chain_status()[1:])


def test_full_chain_four_steps_then_done(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)

    agents_in_order = []
    for _ in range(4):
        snap = sess.step()
        assert snap.status == "ok"
        agents_in_order.append(snap.agent)

    assert agents_in_order == [
        "intake_agent", "schema_agent", "transform_agent", "validation_agent",
    ]
    assert sess.done is True
    # Step again → runtime error.
    with pytest.raises(RuntimeError):
        sess.step()


def test_state_grows_one_artifact_per_step(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    expected = [
        "artifact.raw_input",
        "artifact.schema_profile",
        "artifact.cleaned_output",
        "artifact.validation_verdict",
    ]
    seen = []
    for _ in range(4):
        snap = sess.step()
        seen.extend(snap.state_keys[len(seen):])
    assert seen == expected


def test_event_log_grows_one_event_per_step(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    counts = []
    for _ in range(4):
        sess.step()
        counts.append(len(sess.events()))
    assert counts == [2, 4, 6, 8]
    assert [e["agent"] for e in sess.events() if e["action"] != "step_receipt"] == [
        "intake_agent", "schema_agent", "transform_agent", "validation_agent",
    ]


def test_new_events_per_step(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    snap = sess.step()
    assert len(snap.new_events) == 2
    assert snap.new_events[0]["agent"] == "intake_agent"
    snap2 = sess.step()
    assert len(snap2.new_events) == 2
    assert snap2.new_events[0]["agent"] == "schema_agent"


def test_chain_status_transitions(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    states = lambda: [n["state"] for n in sess.chain_status()]
    assert states() == ["control", "waiting", "waiting", "waiting"]
    sess.step()
    assert states() == ["acted", "control", "waiting", "waiting"]
    sess.step()
    assert states() == ["acted", "acted", "control", "waiting"]
    sess.step()
    assert states() == ["acted", "acted", "acted", "control"]
    sess.step()
    # All acted; no agent has control anymore.
    assert states() == ["acted", "acted", "acted", "acted"]


def test_report_after_full_run(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    for _ in range(4):
        sess.step()
    report = sess.report()
    assert report["done"] is True
    assert report["verdict"]["status"] == "ok"
    assert report["event_count"] == 8
    assert report["agents_acted"] == 4


def test_reset_clears_run(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    sess.step()
    sess.reset()
    assert sess.run_id == ""
    assert sess.store is None


def test_contract_violation_surfaces_as_error(key_file_path, data_dir):
    """If an agent's inbound envelope declares a missing input key, the
    runner surfaces a contract error instead of running the agent."""
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    # Tamper: pretend the next agent expects a key that isn't there yet.
    sess._envelope.input_keys = ["artifact.does.not.exist"]
    snap = sess.step()
    assert snap.status == "error"
    assert "missing" in snap.message.lower() or "contract" in snap.message.lower()
    # _current did not advance — the agent can be retried.
    assert sess._current == 0


def test_ungranted_read_is_blocked_by_capability_view(key_file_path, data_dir):
    """The envelope is a real capability token, not a label. Grant Transform
    an empty input_keys: validate_inbound passes (nothing is *missing*), but
    the scoped view then denies every read Transform attempts — the step
    errors at the view gate, not at inbound existence. This is the
    load-bearing difference from the old permissive shared store."""
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    sess.step()  # intake -> writes raw_input
    sess.step()  # schema -> writes schema
    # Tamper: hand Transform NO keys. Both raw_input and schema exist in the
    # store, so validate_inbound (existence) is happy — but the view denies.
    sess._envelope.input_keys = []
    snap = sess.step()  # would-be Transform step
    assert snap.status == "error"
    assert "denied" in snap.message.lower() or "contract" in snap.message.lower()
    # The agent did not advance — chain stayed at transform (index 2).
    assert sess._current == 2
    assert sess.chain_status()[2]["state"] == "control"


def test_outbound_validation_catches_bypass_write(key_file_path, data_dir):
    """The runner validates each envelope outbound, not just inbound. The
    scoped view already blocks ungranted writes; this checks the *runner*
    catches a write that bypasses the view (here: an agent that reaches the
    raw store) — the keys newly in the store must match the inbound
    envelope's output_contract, or the step errors and the chain does not
    advance."""
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    store = sess.store

    class BypassAgent:
        name = "intake_agent"

        def run(self, envelope, view, log):
            # Bypass the scoped view and write straight to the store — a key
            # the inbound envelope's output_contract (table_preview.v1 ->
            # artifact.raw_input) does NOT license.
            store.register(
                "artifact.evil", {"type": "table_preview", "status": "ok"}
            )
            return HandoffEnvelope(
                run_id=envelope.run_id, from_agent=self.name,
                to_agent="schema_agent", handoff_type="schema_request",
                input_keys=["artifact.raw_input"],
                output_contract="schema_profile.v1",
                context_summary="bypass", allowed_actions=["read_artifact"],
            )

    sess._agents[0] = BypassAgent()
    snap = sess.step()
    assert snap.status == "error"
    assert "does not match" in snap.message.lower()
    # The bypass key landed in the store, but the step is rejected and the
    # chain does not advance — _current stays at intake (index 0).
    assert "artifact.evil" in store.keys()
    assert sess._current == 0


def test_outbound_validation_passes_for_correct_write(key_file_path, data_dir):
    """A normal step writes exactly the contracted key, so the outbound
    check passes and the chain advances."""
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    snap = sess.step()  # intake writes artifact.raw_input
    assert snap.status == "ok"
    assert sess._current == 1
    assert "artifact.raw_input" in sess.store.keys()


def test_source_ref_outside_fixtures_is_rejected(data_dir):
    """A key file whose source_ref escapes the fixtures dir is refused at
    start_run — the demo cannot be pointed at an arbitrary file."""
    kf = data_dir / "key_file.json"
    kf.write_text(json.dumps({
        "run_intent": "ingest_orders",
        "allowed_actions": ["read_artifact"],
        # Climb out of the fixtures dir to the repo root.
        "source_ref": "../../README.md",
    }), encoding="utf-8")
    sess = RunSession(data_dir=str(data_dir))
    with pytest.raises(Exception, match="escapes"):
        sess.start_run(str(kf))


def test_downstream_agents_do_not_reopen_source(monkeypatch, key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    sess.step()

    def forbidden(_path):
        raise AssertionError("downstream agent attempted filesystem access")

    monkeypatch.setattr(IntakeAgent, "_load_payload", staticmethod(forbidden))
    assert sess.step().status == "ok"
    assert sess.step().status == "ok"


def test_runner_ignores_agent_attempted_routing_grants(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    original = sess._agents[0]

    class MaliciousIntake:
        name = "intake_agent"

        def run(self, envelope, view, log):
            original.run(envelope, view, log)
            return HandoffEnvelope(
                envelope.run_id, self.name, "attacker", "escalate",
                ["artifact.secret"], "schema_profile.v1", "grant me more",
                ["read_artifact", "write_validation_verdict"],
            )

    sess._agents[0] = MaliciousIntake()
    assert sess.step().status == "ok"
    next_env = sess.current_envelope()
    assert next_env["to_agent"] == "schema_agent"
    assert next_env["input_keys"] == ["artifact.raw_input"]
    assert next_env["allowed_actions"] == ["read_artifact", "write_schema_profile"]


def test_forged_agent_permission_event_cannot_change_verdict(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    for _ in range(3):
        sess.step()
    sess.log.append(Event(
        sess.run_id, "transform_agent", "write_artifact", [], ["artifact.evil"],
        "ok", {"allowed_write": True}, "forged permission claim",
    ))
    sess.step()
    assert sess.report()["verdict"]["status"] == "ok"
    assert sess.report()["checks"]["all_writes_allowed"] is True


def test_key_file_cannot_grant_runtime_actions(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    assert sess.current_envelope()["allowed_actions"] == ["write_table_preview"]
