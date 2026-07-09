"""Streamlit UI for the agent-network demo — a single one-screen dashboard.

Run from the repo root::

    streamlit run agent_network_demo/streamlit_app.py

The thesis is **agents pass keys (references), not blobs**. The envelope
between agents is a real *capability token*: an agent may read only the keys it
was handed (``input_keys``) and write only the one key its ``output_contract``
licenses — enforced by the scoped ``StoreView`` the runner hands each agent.

Everything fits on one screen under one header:
  - Top bar: run id + Start / Step / Reset + key file + verdict chip.
  - Spine: the four-agent pipeline with per-step badges.
  - Main row: the interactive **relation map** (streamlit_agraph) on the left,
    and on the right the **key-handoff strip** (which keys just moved between
    agents) plus a click-to-inspect detail panel.
  - Bottom row: compact state-registry cards (the shared store by key) and the
    append-only event log.
  - A verdict banner once the ShadowJudge has acted.

Node kinds: agents (dots) and artifacts (boxes). Edge kinds: writes
(agent → artifact), reads (artifact → agent, i.e. the key being passed), and
handoffs (agent → agent). As you step, nodes/edges fill in; click any node to
inspect it.
"""

from __future__ import annotations

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
from agent_network_demo.contracts import write_key_for
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
# Detail panel (click a node)
# ---------------------------------------------------------------------------

def render_detail(sess: RunSession, sel: Optional[str]) -> None:
    """Inspect a clicked node: an agent or an artifact key."""
    if not sel:
        st.info("⬅ Click a node in the map to inspect it.")
        return
    agent_ids = {a[0] for a in ui.AGENTS}
    if sel in agent_ids:
        chain = {n["agent"]: n["state"] for n in sess.chain_status()}
        env = _envelope_for_agent(sess, sel)
        ui.agent_detail(sel, chain.get(sel, "waiting"), env, sess.events())
    elif sess.store.has(sel):
        ui.artifact_detail(sel, sess.store.get(sel))
    else:
        st.info(f"Node `{sel}` has no detail yet.")


# ---------------------------------------------------------------------------
# Top bar (run controls)
# ---------------------------------------------------------------------------

def render_top_bar(sess: Optional[RunSession]) -> None:
    """One row: run id · Start · Step · Reset · key file · verdict chip.
    Returns nothing — button clicks are handled here with st.rerun()."""
    c_id, c_start, c_step, c_reset, c_kf, c_verd = st.columns(
        [1.0, 0.75, 0.75, 0.75, 1.7, 0.9])

    with c_id:
        if sess and sess.run_id:
            st.markdown(
                f'<span class="and-chip and-runid">{sess.run_id}</span>',
                unsafe_allow_html=True)
            if sess.done:
                st.markdown('<span class="and-chip" style="margin-top:4px">done</span>',
                            unsafe_allow_html=True)
        else:
            st.markdown('<span class="and-chip" style="color:#94a3b8">no run</span>',
                        unsafe_allow_html=True)

    with c_start:
        start_clicked = st.button("▶ Start", use_container_width=True)
    with c_step:
        step_clicked = st.button("⏭ Step", use_container_width=True)
    with c_reset:
        reset_clicked = st.button("↺ Reset", use_container_width=True)
    with c_kf:
        key_file = st.text_input("Key file", value=DEFAULT_KEY_FILE,
                                 label_visibility="collapsed")

    with c_verd:
        if sess and sess.done:
            v = sess.report().get("verdict") or {}
            status = v.get("status", "—")
            col = {"ok": ui.GREEN, "warn": ui.AMBER}.get(status, ui.RED)
            st.markdown(
                f'<span class="and-verdchip" style="background:{col}">'
                f'{status.upper()}</span>',
                unsafe_allow_html=True)
        elif sess and sess.error:
            st.markdown(
                f'<span class="and-verdchip" style="background:{ui.RED}">ERROR</span>',
                unsafe_allow_html=True)

    # --- handle clicks ---------------------------------------------------
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


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Agents pass keys, not blobs", layout="wide")
    ui.inject_css()
    ui.hero(
        "Agents pass keys, not blobs",
        "A deterministic multi-agent demo. Agents hand each other *references* "
        "into a shared artifact store — never the content. The envelope is a "
        "real capability token: an agent can read only the keys it was handed.",
        compact=True,
    )

    sess = get_session()

    # --- top bar (controls) ----------------------------------------------
    render_top_bar(sess)
    if sess and sess.error:
        st.caption(f"last error: {sess.error}")

    sess = get_session()

    # --- main area -------------------------------------------------------
    if sess is None:
        st.info(
            "No active run. Click **▶ Start** above, then **⏭ Step** to walk "
            "the chain: Intake → Schema → Transform → Validation. Watch the "
            "relation map fill in as keys are written and read, and the "
            "key-handoff strip show which references move between agents."
        )
        return

    ui.spine(spine_states(sess), spine_badges(sess))

    # Main row: relation map | key-handoff strip + detail panel.
    graph_col, detail_col = st.columns([2.3, 1])
    with graph_col:
        ui.map_legend()
        nodes, edges = build_graph(sess)
        cfg = Config(
            width=840, height=480, directed=True, physics=False,
            hierarchical=True, direction="LR", nodeSpacing=130, levelSeparation=160,
            nodeHighlightBehavior=True, highlightColor=ui.BLUE,
        )
        clicked = agraph(nodes=nodes, edges=edges, config=cfg)
        if clicked:
            st.session_state["selected"] = clicked
    with detail_col:
        env = sess.current_envelope()
        ui.key_handoff(env, write_key_for(env.get("output_contract", "")), sess.store)
        st.markdown("")  # small breath
        sel = st.session_state.get("selected")
        render_detail(sess, sel)

    # Bottom row: state registry cards | event log.
    st.markdown("")  # small gap
    bl, br = st.columns([1, 1])
    with bl:
        ui.section_header("State registry",
                          "The shared artifact store — content lives here by key, "
                          "not in the envelopes between agents.")
        ui.state_cards(sess.state())
    with br:
        ui.section_header("Event log",
                          "Append-only audit trail: every action with its input "
                          "keys, output keys, status, and checks.")
        ui.event_rows(sess.events(), scroll=True)

    # Verdict banner once the ShadowJudge has acted.
    if sess.done:
        v = sess.report().get("verdict")
        if v:
            ui.verdict_banner(v)


if __name__ == "__main__":  # pragma: no cover
    main()