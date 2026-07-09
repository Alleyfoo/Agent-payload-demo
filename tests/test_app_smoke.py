"""Smoke test for the Streamlit UI, driven through streamlit.testing.AppTest.

Exercises the killer demo click sequence (Start → Step ×4) on the one-screen
dashboard and the click-to-inspect detail panel, asserting no exceptions and a
green verdict. Requires streamlit + streamlit_agraph (both in requirements.txt).
"""

from __future__ import annotations

import os

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

APP_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "agent_network_demo", "streamlit_app.py")


@pytest.fixture
def app():
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    assert not at.exception, f"startup: {at.exception}"
    return at


def test_top_bar_has_controls(app):
    # Start, Step, Reset, Replay live in the top bar (main area), not sidebar.
    assert len(app.button) == 4
    assert len(app.sidebar.button) == 0


def test_autostarts_full_run_on_load(app):
    # A fresh visit loads an already-completed run, not an empty page.
    sess = app.session_state["session"]
    assert sess is not None
    assert sess.run_id
    assert sess.done is True
    assert sess.report()["verdict"]["status"] == "ok"


def test_reset_clears_without_reautostarting(app):
    # Reset leaves the page clean; it must not instantly auto-run again.
    app.button[2].click().run()  # Reset
    assert not app.exception, f"reset: {app.exception}"
    assert app.session_state["session"] is None


def test_full_run_via_clicks(app):
    app.button[0].click().run()  # Start
    assert not app.exception, f"start: {app.exception}"
    sess = app.session_state["session"]
    assert sess and sess.run_id

    for i in range(4):
        app.button[1].click().run()  # Step
        assert not app.exception, f"step {i+1}: {app.exception}"

    assert app.session_state["session"].done
    rep = app.session_state["session"].report()
    assert rep["verdict"]["status"] == "ok"
    assert rep["event_count"] == 4


def test_detail_panel_for_artifact(app):
    app.button[0].click().run()  # Start
    assert not app.exception
    app.session_state["selected"] = "artifact.raw_input"
    app.run()
    assert not app.exception, f"detail panel: {app.exception}"


def test_detail_panel_for_agent(app):
    app.button[0].click().run()
    assert not app.exception
    app.session_state["selected"] = "schema_agent"
    app.run()
    assert not app.exception, f"agent detail: {app.exception}"