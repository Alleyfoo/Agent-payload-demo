"""Tests for the append-only event log."""

from __future__ import annotations

import json
import os

from agent_network_demo.event_log import Event, EventLog


def test_append_assigns_event_id_and_writes_jsonl(data_dir):
    log = EventLog("run_001", data_dir=str(data_dir))
    e = log.append(Event(run_id="run_001", agent="intake_agent",
                         action="write_artifact", output_keys=["artifact.x"]))
    assert e.event_id == "evt_001"
    assert e.timestamp  # ISO-8601
    assert len(log) == 1
    log.close()
    path = os.path.join(str(data_dir), "events_run_001.jsonl")
    lines = open(path, encoding="utf-8").read().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_id"] == "evt_001"
    assert parsed["agent"] == "intake_agent"


def test_event_ids_increment(data_dir):
    log = EventLog("run_002", data_dir=str(data_dir))
    a = log.append(Event(run_id="run_002", agent="a", action="x"))
    b = log.append(Event(run_id="run_002", agent="b", action="y"))
    assert a.event_id == "evt_001"
    assert b.event_id == "evt_002"


def test_for_run_filters(data_dir):
    log = EventLog("run_003", data_dir=str(data_dir))
    log.append(Event(run_id="run_003", agent="a", action="x"))
    log.append(Event(run_id="other", agent="b", action="y"))
    assert len(log.for_run("run_003")) == 1
    assert len(log.for_run("other")) == 1
    assert len(log.all()) == 2
    log.close()


def test_as_dicts_round_trips(data_dir):
    log = EventLog("run_004", data_dir=str(data_dir))
    log.append(Event(run_id="run_004", agent="a", action="x",
                     checks={"ok": True}))
    d = log.as_dicts()
    assert d[0]["checks"] == {"ok": True}
    assert d[0]["event_id"] == "evt_001"
    log.close()


def test_read_file_reads_back_jsonl(data_dir):
    log = EventLog("run_005", data_dir=str(data_dir))
    log.append(Event(run_id="run_005", agent="a", action="x"))
    log.close()
    path = os.path.join(str(data_dir), "events_run_005.jsonl")
    read = EventLog.read_file(path)
    assert len(read) == 1
    assert read[0]["agent"] == "a"


def test_read_file_missing_returns_empty():
    assert EventLog.read_file("does-not-exist.jsonl") == []