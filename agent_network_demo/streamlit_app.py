"""Streamlit UI for the agent-network demo.

Run from the repo root::

    streamlit run agent_network_demo/streamlit_app.py

Layout:
  - Left panel: choose key file (default fixture), Start run, Step next
    agent, Reset.
  - Middle: agent chain (control / acted / waiting), current handoff
    envelope, shared state keys.
  - Right / tabs: Run | Graph | State registry | Event log | Agent
    messages | Final report.

The RunSession lives in ``st.session_state`` so stepping is interactive.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

import streamlit as st

# Ensure the repo root is on sys.path so `agent_network_demo` is importable
# whether this file is run as a script (`streamlit run
# agent_network_demo/streamlit_app.py`, which puts the *script* dir on the
# path, not the repo root) or imported as a package. Without this, the
# package's absolute imports fail on Streamlit Community Cloud.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_network_demo.demo_runner import RunSession, StepSnapshot

DEFAULT_KEY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "key_file.json"
)

# Consistent colors for chain states.
STATE_STYLE = {
    "acted": ("✅ acted", "off"),
    "control": ("🎯 control", "on"),
    "waiting": ("⏳ waiting", "off"),
}


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def get_session() -> RunSession | None:
    return st.session_state.get("session")


def require_session() -> RunSession:
    sess = get_session()
    if sess is None:
        st.stop()
    return sess


# ---------------------------------------------------------------------------
# Rendering pieces
# ---------------------------------------------------------------------------

def render_chain(chain_status: list[dict[str, str]]) -> None:
    cols = st.columns(len(chain_status))
    for col, node in zip(cols, chain_status):
        label, on = STATE_STYLE.get(node["state"], (node["state"], "off"))
        with col:
            st.metric(node["agent"], label)
            st.caption(f"state: {node['state']}")


def render_envelope(env: Dict[str, Any]) -> None:
    st.markdown("**Current handoff envelope**")
    st.code(json.dumps(env, indent=2, ensure_ascii=False), language="json")


def render_state(state: Dict[str, Any]) -> None:
    if not state:
        st.info("No artifacts yet. Run the first agent to seed the store.")
        return
    for key, art in state.items():
        with st.expander(f"{key}  —  `{art.get('type')}` · {art.get('status')}",
                         expanded=False):
            show = {k: v for k, v in art.items() if k != "source_hash"}
            show["source_hash"] = art.get("source_hash", "")[:12] + "…"
            st.json(show)


def render_events(events: list[dict[str, Any]]) -> None:
    if not events:
        st.info("No events yet.")
        return
    for ev in reversed(events):
        status_emoji = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(
            ev.get("status"), "•")
        st.markdown(
            f"{status_emoji} `{ev['event_id']}` **{ev['agent']}** · "
            f"{ev['action']}  →  out: `{ev.get('output_keys', [])}`  "
            f"(in: `{ev.get('input_keys', [])}`)"
        )
        if ev.get("checks"):
            st.caption("checks: " + json.dumps(ev["checks"], ensure_ascii=False))
        if ev.get("message"):
            st.caption(ev["message"])


def render_report(report: Dict[str, Any]) -> None:
    if not report.get("done"):
        st.info("Run the full chain to produce the final report.")
        return
    verdict = report.get("verdict") or {}
    status = verdict.get("status", "—")
    st.metric("Verdict", status)
    if report.get("reasons"):
        st.markdown("**Reasons**")
        for r in report["reasons"]:
            st.markdown(f"- {r}")
    if report.get("checks"):
        st.markdown("**Checks**")
        st.json(report["checks"])
    cols = st.columns(3)
    cols[0].metric("Events", report.get("event_count", 0))
    cols[1].metric("Agents acted", report.get("agents_acted", 0))
    cols[2].metric("Total agents", report.get("total_agents", 0))


def render_messages(events: list[dict[str, Any]]) -> None:
    """Render events as agent 'messages' (one per agent action)."""
    if not events:
        st.info("No agent messages yet.")
        return
    for ev in events:
        who = ev["agent"]
        body = ev.get("message") or ev["action"]
        st.chat_message("assistant", avatar="🤖").markdown(
            f"**{who}** ({ev['action']}): {body}"
        )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Agents pass keys, not blobs",
        layout="wide",
    )
    st.title("Agents pass keys, not blobs")
    st.caption(
        "A deterministic multi-agent demo. Agents hand each other *references* "
        "into a shared artifact store — never the content itself."
    )

    # --- left control panel ------------------------------------------------
    with st.sidebar:
        st.header("Run controls")
        key_file = st.text_input("Key file path", value=DEFAULT_KEY_FILE)

        c1, c2 = st.columns(2)
        start_clicked = c1.button("▶ Start run", use_container_width=True)
        step_clicked = c2.button("⏭ Step next agent", use_container_width=True)
        reset_clicked = st.button("↺ Reset run", use_container_width=True)

        sess = get_session()

        if start_clicked:
            new_sess = RunSession(data_dir="data")
            try:
                rid = new_sess.start_run(key_file)
                st.session_state["session"] = new_sess
                st.session_state["last_step"] = None
                st.toast(f"Started {rid}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to start run: {exc}")
            st.rerun()

        if reset_clicked:
            if sess is not None:
                sess.reset()
            st.session_state["session"] = None
            st.session_state["last_step"] = None
            st.rerun()

        if step_clicked:
            sess = get_session()
            if sess is None:
                st.warning("Start a run first.")
            else:
                try:
                    snap = sess.step()
                    st.session_state["last_step"] = snap
                except RuntimeError as exc:
                    st.warning(str(exc))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Step failed: {exc}")
            st.rerun()

        st.divider()
        sess = get_session()
        if sess is not None and sess.run_id:
            st.markdown(f"**run_id:** `{sess.run_id}`")
            st.markdown(f"**done:** `{sess.done}`")
            if sess.error:
                st.error(sess.error)

    sess = get_session()

    # --- main area ---------------------------------------------------------
    if sess is None:
        st.info(
            "No active run. Click **▶ Start run** in the sidebar, then "
            "**⏭ Step next agent** to walk the chain: Intake → Schema → "
            "Transform → Validation."
        )
        st.markdown(
            "The key file lives at "
            f"`{os.path.relpath(DEFAULT_KEY_FILE)}` and points the first "
            "agent at the sample payload."
        )
        return

    chain = sess.chain_status()
    st.subheader("Agent chain")
    render_chain(chain)

    tabs = st.tabs([
        "Run", "Graph", "State registry", "Event log",
        "Agent messages", "Final report",
    ])

    with tabs[0]:
        col_a, col_b = st.columns([1, 1])
        with col_a:
            st.subheader("Current envelope")
            render_envelope(sess.current_envelope())
        with col_b:
            st.subheader("Shared state keys")
            keys = sess.store.keys() if sess.store else []
            if keys:
                for k in keys:
                    st.code(k)
            else:
                st.info("Store is empty.")

    with tabs[1]:
        st.subheader("Chain graph")
        render_chain(chain)
        st.caption("🎯 control = who runs next · ✅ acted · ⏳ waiting")

    with tabs[2]:
        st.subheader("State registry")
        render_state(sess.state())

    with tabs[3]:
        st.subheader("Event log (append-only)")
        render_events(sess.events())

    with tabs[4]:
        st.subheader("Agent messages")
        render_messages(sess.events())

    with tabs[5]:
        st.subheader("Final report")
        render_report(sess.report())


if __name__ == "__main__":  # pragma: no cover
    main()