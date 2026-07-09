"""Streamlit UI for the agent-network demo.

Run from the repo root::

    streamlit run agent_network_demo/streamlit_app.py

The centrepiece is an interactive **relation map** (streamlit_agraph) showing
the two node kinds — agents and the artifacts (keys) they pass between them —
and three edge kinds: writes (agent → artifact), reads (artifact → agent,
i.e. the key being passed), and handoffs (agent → agent). As you step the
chain, nodes and edges fill in: acted agents turn green, written artifacts
light up, traversed edges get colour. Click any node to open a detail panel.

Layout:
  - Sidebar: choose key file, Start / Step / Reset.
  - Hero + spine (the agent pipeline with per-step badges).
  - Tabs: Network (graph + detail) | Chain | State registry | Event log |
    Agent messages | Final report.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config

# Ensure the repo root is on sys.path so the package imports resolve whether
# this file is run as a script (Streamlit Cloud) or as a package.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_network_demo import ui
from agent_network_demo.demo_runner import RunSession

DEFAULT_KEY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "key_file.json"
)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_session() -> Optional[RunSession]:
    return st.session_state.get("session")


# ---------------------------------------------------------------------------
# Relation map (the centrepiece)
# ---------------------------------------------------------------------------

def build_graph(sess: RunSession):
    """Build agraph nodes + edges from the current session state.

    Nodes: 4 agents (dots) + 4 artifact keys (boxes). Agents are always shown
    (styled by chain state); artifacts are coloured if written, ghosted if not.
    Edges: writes (agent→artifact), reads (artifact→agent), handoffs
    (agent→agent). Traversed edges are coloured; pending edges are ghosted.
    """
    chain = {n["agent"]: n["state"] for n in sess.chain_status()}
    store = sess.store

    def agent_state(aid: str) -> str:
        return chain.get(aid, "waiting")

    def artifact_status(key: str) -> Optional[str]:
        if store.has(key):
            return store.get(key).get("status")
        return None

    # --- nodes ---
    nodes: List[Node] = []
    for aid, _icon, label, _sub in ui.AGENTS:
        st_ = agent_state(aid)
        sc, bg, _lbl = ui.AGENT_STATE.get(st_, (ui.SLATE, ui.GHOST_BG, st_))
        nodes.append(Node(
            id=aid, label=label, title=f"{label} · {st_}",
            shape="dot", size=26, borderWidth=3,
            color={"background": bg, "border": sc, "highlight": {"background": bg, "border": ui.BLUE}},
        ))

    for key, _short, _icon, label, tint, accent in ui.ARTIFACTS:
        status = artifact_status(key)
        if status is None:
            bg, border = ui.GHOST_BG, ui.GHOST
            title = f"{label} · not written yet"
        else:
            bg, border = tint, ui.ARTIFACT_STATUS.get(status, ui.MUTED)
            title = f"{label} · {status}"
        nodes.append(Node(
            id=key, label=label, title=title,
            shape="box", borderWidth=3 if status else 2,
            color={"background": bg, "border": border,
                   "highlight": {"background": bg, "border": ui.BLUE}},
        ))

    # --- edges ---
    edges: List[Edge] = []

    def edge(cid: str, source: str, target: str, label: str,
             traversed: bool, color_traversed: str, glyph: str = "") -> None:
        color = color_traversed if traversed else ui.GHOST
        edges.append(Edge(
            source=source, target=target, label=(glyph + label) if traversed and glyph else "",
            color=color, width=2 if traversed else 1,
            dashes=not traversed, arrowColor={"color": color, "highlight": ui.BLUE},
        ))

    # writes: agent -> artifact
    for aid, key in ui.WRITES.items():
        status = artifact_status(key)
        traversed = status is not None
        # colour the write edge by the artifact status when present
        col = ui.ARTIFACT_STATUS.get(status, ui.GREEN) if traversed else ui.GREEN
        edge(f"w-{aid}", aid, key, "writes", traversed, col)

    # reads: artifact -> agent (the keys that travel between agents)
    for aid, keys in ui.READS.items():
        for key in keys:
            traversed = agent_state(aid) == "acted"
            edge(f"r-{aid}-{key}", key, aid, "reads", traversed, ui.BLUE)

    # handoffs: agent -> agent
    for src, dst, htype in ui.HANDOFFS:
        traversed = agent_state(src) == "acted"
        edge(f"h-{src}-{dst}", src, dst, htype, traversed, ui.NAVY)

    return nodes, edges


def render_network_tab(sess: RunSession) -> None:
    ui.section_header(
        "Agent Network — the relation map",
        "Agents (dots) pass keys (boxes) to each other — never the content. "
        "Fill = type, border = status, arrows show writes / reads / handoffs. "
        "Click a node to inspect it.",
    )
    ui.map_legend()

    nodes, edges = build_graph(sess)
    cfg = Config(
        width=820, height=560, directed=True, physics=False,
        hierarchical=True, direction="LR", nodeSpacing=130, levelSeparation=170,
        nodeHighlightBehavior=True, highlightColor=ui.BLUE,
    )
    graph_col, detail_col = st.columns([2.1, 1])
    with graph_col:
        clicked = agraph(nodes=nodes, edges=edges, config=cfg)
        if clicked:
            st.session_state["selected"] = clicked
    with detail_col:
        sel = st.session_state.get("selected")
        if not sel:
            st.info("⬅ Click a node to open its detail panel.")
            return
        agent_ids = {a[0] for a in ui.AGENTS}
        if sel in agent_ids:
            chain = {n["agent"]: n["state"] for n in sess.chain_status()}
            # find an envelope describing this agent: the envelope whose
            # to_agent == sel (inbound), else the one whose from_agent == sel.
            env = _envelope_for_agent(sess, sel)
            ui.agent_detail(sel, chain.get(sel, "waiting"), env, sess.events())
        elif sess.store.has(sel):
            ui.artifact_detail(sel, sess.store.get(sel))
        else:
            st.info(f"Node `{sel}` has no detail yet.")


def _envelope_for_agent(sess: RunSession, aid: str) -> Dict[str, Any]:
    """Best envelope to describe an agent: its inbound (to_agent == aid) if
    available in the event history, else the current envelope if it targets
    aid, else the outbound envelope it produced (from_agent == aid)."""
    env = sess.current_envelope()
    if env.get("to_agent") == aid or env.get("from_agent") == aid:
        return env
    # Search event log for an envelope hint via the agent's write event.
    for e in sess.events():
        if e.get("agent") == aid:
            return {
                "from_agent": aid,
                "to_agent": "—",
                "handoff_type": e.get("action", ""),
                "output_contract": ", ".join(e.get("output_keys", [])),
                "input_keys": e.get("input_keys", []),
                "allowed_actions": [],
            }
    return env


# ---------------------------------------------------------------------------
# Spine badges
# ---------------------------------------------------------------------------

def spine_badges(sess: RunSession) -> Dict[str, List[str]]:
    """Per-agent badge HTML for the spine: state + event count + output key."""
    chain = {n["agent"]: n["state"] for n in sess.chain_status()}
    events = sess.events()
    out: Dict[str, List[str]] = {}
    for aid, _ic, _lbl, _sub in ui.AGENTS:
        st_ = chain.get(aid, "waiting")
        sc, bg, slbl = ui.AGENT_STATE.get(st_, (ui.SLATE, ui.GHOST_BG, st_))
        n_ev = sum(1 for e in events if e.get("agent") == aid)
        bs = [ui.badge(slbl, sc, bg)]
        if n_ev:
            bs.append(ui.badge(f"{n_ev} event{'s' if n_ev != 1 else ''}", ui.MUTED, "#eef2f7"))
        wkey = ui.WRITES.get(aid)
        if wkey and sess.store.has(wkey):
            bs.append(ui.badge("✓ wrote", ui.GREEN, "#e8f7ee"))
        out[aid] = bs
    return out


def spine_states(sess: RunSession) -> Dict[str, str]:
    return {n["agent"]: n["state"] for n in sess.chain_status()}


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def render_chain_tab(sess: RunSession) -> None:
    ui.section_header("Chain",
                      "The four agents in order — who has control, who acted, "
                      "who is waiting. Each card shows the contract it produces "
                      "and the keys it reads.")
    # envelopes by to_agent for the flow cards
    env_by_to: Dict[str, Dict[str, Any]] = {}
    env = sess.current_envelope()
    if env:
        env_by_to[env.get("to_agent", "")] = env
    ui.chain_flow(sess.chain_status(), env_by_to)
    st.caption("🎯 control = runs next · ✅ acted · ⏳ waiting")
    st.markdown("**Current handoff envelope** (references, not content):")
    st.code(json.dumps(sess.current_envelope(), indent=2, ensure_ascii=False),
            language="json")


def render_state_tab(sess: RunSession) -> None:
    ui.section_header("State registry",
                      "The shared artifact store — content lives here by key, "
                      "not in the envelopes between agents.")
    state = sess.state()
    if not state:
        st.info("No artifacts yet. Run the first agent to seed the store.")
        return
    for key, art in state.items():
        with st.expander(f"{key}  —  `{art.get('type')}` · {art.get('status')}"):
            show = {k: v for k, v in art.items() if k != "source_hash"}
            show["source_hash"] = (art.get("source_hash") or "")[:12] + "…"
            st.json(show)


def render_events_tab(sess: RunSession) -> None:
    ui.section_header("Event log (append-only audit trail)",
                      "Every agent action recorded with its input keys, output "
                      "keys, status, and checks.")
    ui.event_rows(sess.events())


def render_messages_tab(sess: RunSession) -> None:
    ui.section_header("Agent messages",
                      "The same trail, narrated as one message per agent action.")
    events = sess.events()
    if not events:
        st.info("No agent messages yet.")
        return
    for ev in events:
        body = ev.get("message") or ev["action"]
        st.chat_message("assistant", avatar="🤖").markdown(
            f"**{ev['agent']}** ({ev['action']}): {body}"
        )


def render_report_tab(sess: RunSession) -> None:
    ui.section_header("Final report", "The human-readable receipt once the "
                      "ShadowJudge has acted.")
    report = sess.report()
    if not report.get("done"):
        st.info("Run the full chain to produce the final report.")
        return
    verdict = report.get("verdict") or {}
    status = verdict.get("status", "—")
    c1, c2, c3 = st.columns(3)
    c1.metric("Verdict", status)
    c2.metric("Events", report.get("event_count", 0))
    c3.metric("Agents acted", f"{report.get('agents_acted', 0)}/{report.get('total_agents', 0)}")
    if report.get("reasons"):
        st.markdown("**Reasons**")
        for r in report["reasons"]:
            st.markdown(f"- {r}")
    if report.get("checks"):
        st.markdown("**Checks**")
        st.json(report["checks"])


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Agents pass keys, not blobs", layout="wide")
    ui.inject_css()
    ui.hero("Agents pass keys, not blobs",
            "A deterministic multi-agent demo. Agents hand each other *references* "
            "into a shared artifact store — never the content itself.")

    # --- sidebar controls --------------------------------------------------
    with st.sidebar:
        st.header("Run controls")
        key_file = st.text_input("Key file path", value=DEFAULT_KEY_FILE)
        c1, c2 = st.columns(2)
        start_clicked = c1.button("▶ Start", use_container_width=True)
        step_clicked = c2.button("⏭ Step", use_container_width=True)
        reset_clicked = st.button("↺ Reset", use_container_width=True)

        if start_clicked:
            new_sess = RunSession(data_dir="data")
            try:
                rid = new_sess.start_run(key_file)
                st.session_state["session"] = new_sess
                st.session_state["selected"] = None
                st.toast(f"Started {rid}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to start run: {exc}")
            st.rerun()

        if reset_clicked:
            sess = get_session()
            if sess is not None:
                sess.reset()
            st.session_state["session"] = None
            st.session_state["selected"] = None
            st.rerun()

        if step_clicked:
            sess = get_session()
            if sess is None:
                st.warning("Start a run first.")
            else:
                try:
                    sess.step()
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
            if sess.done:
                v = sess.report().get("verdict") or {}
                st.metric("Verdict", v.get("status", "—"))

    sess = get_session()

    # --- main area ---------------------------------------------------------
    if sess is None:
        st.info(
            "No active run. Click **▶ Start** in the sidebar, then **⏭ Step** "
            "to walk the chain: Intake → Schema → Transform → Validation. "
            "Watch the relation map fill in as keys are written and read."
        )
        return

    ui.spine(spine_states(sess), spine_badges(sess))

    tabs = st.tabs(["Network", "Chain", "State registry", "Event log",
                    "Agent messages", "Final report"])
    with tabs[0]:
        render_network_tab(sess)
    with tabs[1]:
        render_chain_tab(sess)
    with tabs[2]:
        render_state_tab(sess)
    with tabs[3]:
        render_events_tab(sess)
    with tabs[4]:
        render_messages_tab(sess)
    with tabs[5]:
        render_report_tab(sess)


if __name__ == "__main__":  # pragma: no cover
    main()