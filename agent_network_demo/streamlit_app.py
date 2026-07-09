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
from agent_network_demo.contracts import write_key_for
from agent_network_demo.demo_runner import RunSession

DEFAULT_KEY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "key_file.json"
)


def list_key_files() -> List[str]:
    """The key files the demo may run — every JSON file *inside the fixtures
    dir* that looks like a key file (carries ``source_ref`` +
    ``allowed_actions``). The UI offers only these, never a free-text path:
    the public demo must not have a "please type a server path" box next to a
    page about safe agent payloads. The runner confines the chosen key file's
    ``source_ref`` to this same dir, so the whole input surface is bounded."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
    out: List[str] = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "source_ref" in data and "allowed_actions" in data:
            out.append(path)
    return out


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_session() -> Optional[RunSession]:
    return st.session_state.get("session")


def ensure_session_or_autostart() -> Optional[RunSession]:
    """Return the current session, or — on a fresh visit — auto-start and run
    the whole chain so the page loads already populated (full map, key-handoff
    strip, state cards, event log, verdict banner). A visitor gets the whole
    story without clicking anything, then uses Reset + Step to replay it.

    A one-shot: once ``initialized`` is set we never auto-start again, so an
    explicit Reset leaves the page clean instead of instantly refilling."""
    sess = get_session()
    if sess is not None:
        return sess
    if st.session_state.get("initialized"):
        return None
    st.session_state["initialized"] = True
    try:
        new_sess = RunSession(data_dir="data")
        new_sess.start_run(DEFAULT_KEY_FILE)
        for _ in range(len(RunSession.AGENT_NAMES)):
            if new_sess.done:
                break
            new_sess.step()
        st.session_state["session"] = new_sess
        return new_sess
    except Exception as exc:  # noqa: BLE001 - surface, don't crash the page
        st.error(f"Auto-start failed: {exc}")
        return None


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
# Concrete data panel (the real CSV, the real transformation, the real logfile)
# ---------------------------------------------------------------------------

def render_concrete_data(sess: RunSession) -> None:
    """A hidable frame showing the real CSV rows, the real transformation
    (text → typed, coerced cells highlighted), and the real on-disk logfile."""
    raw_key = ui.WRITES["intake_agent"]
    clean_key = ui.WRITES["transform_agent"]
    if not (sess.store.has(raw_key) and sess.store.has(clean_key)):
        return  # need both raw + cleaned to tell the transformation story
    raw = sess.store.get(raw_key)
    cleaned = sess.store.get(clean_key)
    cols = cleaned.get("columns") or raw.get("columns") or []
    raw_rows = raw.get("preview_rows", [])
    cleaned_rows = cleaned.get("preview_rows", [])

    # A cell was "transformed" iff its value changed between raw and cleaned —
    # that covers text→number coercion ("42.50"→42.5) and any trimming.
    coerce_mask: Dict[Any, bool] = {}
    for i, cr in enumerate(cleaned_rows):
        rr = raw_rows[i] if i < len(raw_rows) else {}
        for c in cols:
            if rr.get(c) != cr.get(c):
                coerce_mask[(i, c)] = True

    with st.expander(
        "📄 The real CSV, the real transformation, the real logfile",
        expanded=True,
    ):
        # The store holds the confined *absolute* payload path; show a
        # repo-relative one in the narrative so the story reads cleanly while
        # still pointing at a real on-disk file.
        src = raw.get("source_ref", "")
        display_src = src
        try:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            rel = os.path.relpath(src, repo_root)
            if not (rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel)):
                display_src = rel
        except ValueError:
            pass
        ui.narrative_block(display_src)
        c1, c2 = st.columns(2)
        with c1:
            ui.data_table(
                raw_rows, cols,
                "Raw input (as loaded from the CSV)",
                f"first {len(raw_rows)} of {raw.get('row_count', '?')} rows · "
                "every value is text",
            )
        with c2:
            ui.data_table(
                cleaned_rows, cols,
                "Cleaned output (TransformAgent)",
                f"{cleaned.get('coerced_cells', 0)} cells coerced · "
                "highlighted = text → typed",
                coerce_mask=coerce_mask,
            )
        # The real on-disk logfile.
        path = sess.log_path()
        log_text = ""
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                log_text = fh.read()
        st.markdown(
            f'<div class="and-dtbl" style="margin-top:10px">'
            f'<div class="and-dtbl-h">Logfile (append-only JSONL)</div>'
            f'<div class="and-dtbl-s">{path or "—"}</div></div>',
            unsafe_allow_html=True,
        )
        st.code(log_text or "(empty)", language="json")


# ---------------------------------------------------------------------------
# Keys-vs-paste comparison box (the 1000-pass test)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _comparison(max_passes: int) -> Dict[str, Any]:
    from agent_network_demo.key_vs_paste import compare
    return compare(max_passes=max_passes)


def render_comparison() -> None:
    """A small, deterministic box that showcases *why* passing keys beats
    pasting content: run the real CSV through 1000 handoffs under both
    architectures and compare the drift."""
    m = _comparison(1000)
    end = m["endpoint"]
    shipped = m["base_content_bytes"] * m["max_passes"]
    with st.expander(
        "🔬 Why keys, not paste: the 1000-pass test", expanded=False,
    ):
        st.markdown(
            '<div class="and-narr">'
            'Same real CSV, run through <b>1000 agent-to-agent handoffs</b>. '
            'Passing <b>keys</b> hands references — the content is read from the '
            'shared store and never re-encoded, so it cannot drift no matter how '
            'many agents touch it. Pasting the <b>text</b> re-serializes the whole '
            'table at every boundary; each boundary is a drift opportunity and '
            'they accumulate. With a <i>perfectly reversible</i> serialization, '
            'paste also drifts 0 — but only if every one of the 1000 boundaries '
            'round-trips exactly. One realistic non-reversible boundary (here: a '
            'CSV emitter that pads string cells and a parser that doesn\'t unpad '
            'them) and the errors compound with every pass.'
            '</div>',
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Keys (this demo)", f"{end['keys_errors']:,} errors",
            delta="0 content bytes shipped", delta_color="off",
        )
        c2.metric(
            "Paste — reversible", f"{end['paste_reversible_errors']:,} errors",
            delta=f"{shipped:,} content bytes shipped", delta_color="off",
        )
        c3.metric(
            "Paste — lossy interop", f"{end['paste_lossy_errors']:,} errors",
            delta=f"{shipped:,}+ content bytes shipped", delta_color="off",
        )
        try:
            import pandas as pd
            df = pd.DataFrame(m["series"]).set_index("passes")[
                ["keys_errors", "paste_reversible_errors", "paste_lossy_errors"]
            ]
            df.columns = ["Keys", "Paste (reversible)", "Paste (lossy)"]
            st.line_chart(df, width="stretch", height=220)
        except Exception:  # noqa: BLE001 - chart is decorative
            pass
        st.caption(
            f"Base table {m['base_content_bytes']:,} bytes · {m['row_count']} rows · "
            f"{m['string_cells']} string cells drift every pass in the lossy case "
            f"→ {m['string_cells'] * m['max_passes']:,} cumulative error events "
            f"at {m['max_passes']} passes."
        )


# ---------------------------------------------------------------------------
# Top bar (run controls)
# ---------------------------------------------------------------------------

def render_top_bar(sess: Optional[RunSession]) -> None:
    """One row: run id · Start · Step · Reset · Replay · key file · verdict chip.
    Returns nothing — button clicks are handled here with st.rerun()."""
    c_id, c_start, c_step, c_reset, c_replay, c_kf, c_verd = st.columns(
        [1.0, 0.75, 0.75, 0.75, 0.85, 1.6, 0.9])

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
    with c_replay:
        replay_clicked = st.button("↻ Replay", use_container_width=True)
    with c_kf:
        # A fixed list of bundled key files, never a free-text path — the
        # demo's only input surface is a closed menu, not "type a server path".
        key_files = list_key_files() or [DEFAULT_KEY_FILE]
        idx = key_files.index(DEFAULT_KEY_FILE) if DEFAULT_KEY_FILE in key_files else 0
        key_file = st.selectbox(
            "Key file", options=key_files, index=idx,
            format_func=os.path.basename, label_visibility="collapsed",
        )

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

    if replay_clicked:
        # The "watch the log grow" story in one click: reset, start a fresh
        # run, but do NOT auto-step — the page loads at step 0 (intake in
        # control) so the visitor then clicks Step to walk the chain.
        old = get_session()
        if old is not None:
            old.reset()
        new_sess = RunSession(data_dir="data")
        try:
            rid = new_sess.start_run(key_file)
            st.session_state["session"] = new_sess
            st.session_state["selected"] = None
            st.toast(f"Replay started: {rid}. Click Step to advance.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to start replay: {exc}")
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

    sess = ensure_session_or_autostart()

    # --- top bar (controls) ----------------------------------------------
    render_top_bar(sess)
    if sess and sess.error:
        st.caption(f"last error: {sess.error}")

    sess = get_session()

    # --- the idiot-proof replay hint ------------------------------------
    # The page auto-runs the whole chain on load so a first visitor sees a
    # populated screen. The *best* story is then "watch the log grow", so tell
    # them, in plain words right under the controls, how to replay it slowly.
    if sess and sess.done:
        st.info(
            "This page loaded the **completed run** on first visit — the full "
            "chain already ran so the screen is populated. Click **↻ Replay** "
            "(or **↺ Reset**), then **⏭ Step** to watch the payload move from "
            "agent to agent and the event log grow one row at a time."
        )

    # --- main area -------------------------------------------------------
    if sess is None:
        st.info(
            "Run cleared. Click **▶ Start** to begin a fresh run, then "
            "**⏭ Step** to walk the chain: Intake → Schema → Transform → "
            "Validation. Watch the relation map fill in as keys are written "
            "and read, and the key-handoff strip show which references move "
            "between agents."
        )
        return

    ui.spine(spine_states(sess), spine_badges(sess))

    # Main row — fixed height so clicking nodes / stepping never reflows the
    # page; only the contents inside this box change.
    with st.container(height=520):
        graph_col, detail_col = st.columns([2.3, 1])
        with graph_col:
            ui.map_legend()
            nodes, edges = build_graph(sess)
            cfg = Config(
                width=840, height=452, directed=True, physics=False,
                hierarchical=True, direction="LR", nodeSpacing=130, levelSeparation=160,
                nodeHighlightBehavior=True, highlightColor=ui.BLUE,
            )
            clicked = agraph(nodes=nodes, edges=edges, config=cfg)
            if clicked:
                st.session_state["selected"] = clicked
        with detail_col:
            env = sess.current_envelope()
            ui.key_handoff(env, write_key_for(env.get("output_contract", "")), sess.store)
            st.markdown("")
            sel = st.session_state.get("selected")
            render_detail(sess, sel)

    # Bottom row — fixed height: state registry cards | event log.
    with st.container(height=286):
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

    # Concrete story (hidable): the real CSV, the real transformation, the real logfile.
    render_concrete_data(sess)

    # Why keys beat paste: the 1000-pass comparison (hidable).
    render_comparison()

    # Verdict banner once the ShadowJudge has acted (also carries the replay hint).
    if sess.done:
        v = sess.report().get("verdict")
        if v:
            ui.verdict_banner(v)


if __name__ == "__main__":  # pragma: no cover
    main()