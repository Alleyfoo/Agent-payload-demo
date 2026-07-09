"""Tests for the RunSession: stepping the chain end-to-end."""

from __future__ import annotations

import pytest

from agent_network_demo.demo_runner import RunSession


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
    assert counts == [1, 2, 3, 4]
    assert [e["agent"] for e in sess.events()] == [
        "intake_agent", "schema_agent", "transform_agent", "validation_agent",
    ]


def test_new_events_per_step(key_file_path, data_dir):
    sess = RunSession(data_dir=str(data_dir))
    sess.start_run(key_file_path)
    snap = sess.step()
    assert len(snap.new_events) == 1
    assert snap.new_events[0]["agent"] == "intake_agent"
    snap2 = sess.step()
    assert len(snap2.new_events) == 1
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
    assert report["event_count"] == 4
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