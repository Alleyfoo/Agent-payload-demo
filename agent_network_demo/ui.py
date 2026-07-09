"""Agent-network demo — UI theme and components.

Inspired by The Foundry's design system: Archivo display type, a navy/orange
palette, white cards, status colours, and a horizontal "spine" pipeline. The
centrepiece is an interactive relation map (rendered with streamlit_agraph in
streamlit_app.py); this module supplies the tokens, CSS, and the smaller
presentation components (spine, badges, legends, detail panels).

Pure presentation — all data comes from the runner/session.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Sequence, Tuple

import streamlit as st

# --- Design tokens -----------------------------------------------------------
NAVY = "#0f2a4d"
BLUE = "#2563c9"
ORANGE = "#e8732a"
MUTED = "#5b6b7f"
GREEN = "#2fa86a"
AMBER = "#f1a73b"
RED = "#e5484d"
TEAL = "#0f8a8a"
SLATE = "#94a3b8"
GHOST = "#cdd6e4"   # for not-yet-traversed nodes/edges
GHOST_BG = "#f4f6fa"

# Agent chain metadata: (id, icon, label, subtitle).
AGENTS: List[Tuple[str, str, str, str]] = [
    ("intake_agent", "inbox", "Intake", "Loads the key-file payload"),
    ("schema_agent", "funnel", "Schema", "Infers column types"),
    ("transform_agent", "modify", "Transform", "Cleans & coerces cells"),
    ("validation_agent", "shield", "Validation", "ShadowJudge re-reads the chain"),
]

# Artifact metadata: (key, short, icon, label, tint, accent).
ARTIFACTS: List[Tuple[str, str, str, str, str, str]] = [
    ("artifact.raw_input", "raw_input", "database", "Raw input",
     "#e7f0fb", BLUE),
    ("artifact.schema_profile", "schema_profile", "nodes", "Schema",
     "#dff3f3", TEAL),
    ("artifact.cleaned_output", "cleaned_output", "modify", "Cleaned",
     "#fdeede", ORANGE),
    ("artifact.validation_verdict", "validation_verdict", "shield", "Verdict",
     "#e8f7ee", GREEN),
]

# Who writes what.
WRITES: Dict[str, str] = {
    "intake_agent": "artifact.raw_input",
    "schema_agent": "artifact.schema_profile",
    "transform_agent": "artifact.cleaned_output",
    "validation_agent": "artifact.validation_verdict",
}
# Who reads what (the keys that travel between agents).
READS: Dict[str, List[str]] = {
    "schema_agent": ["artifact.raw_input"],
    "transform_agent": ["artifact.raw_input", "artifact.schema_profile"],
    "validation_agent": ["artifact.raw_input",
                         "artifact.schema_profile",
                         "artifact.cleaned_output"],
}
# Agent -> agent handoffs: (from, to, label).
HANDOFFS: List[Tuple[str, str, str]] = [
    ("intake_agent", "schema_agent", "schema_request"),
    ("schema_agent", "transform_agent", "transform_request"),
    ("transform_agent", "validation_agent", "validation_request"),
]

# Agent state -> (border colour, background tint, label).
AGENT_STATE: Dict[str, Tuple[str, str, str]] = {
    "control": (BLUE, "#e7f0fb", "has control"),
    "acted": (GREEN, "#e8f7ee", "acted"),
    "waiting": (SLATE, "#eef2f7", "waiting"),
}
# Artifact status -> border colour.
ARTIFACT_STATUS: Dict[str, str] = {
    "ok": GREEN, "pending": AMBER, "warn": AMBER, "error": RED,
}

# Minimal inline line-icons (stroke = currentColor).
ICONS: Dict[str, str] = {
    "inbox": '<path d="M3 12h4l2 3h6l2-3h4M3 12V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7M3 12v5a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
    "funnel": '<path d="M3 4h18l-7 8v6l-4 2v-8z"/>',
    "modify": '<path d="M4 20l4-1 10-10-3-3L5 16z"/><path d="M14 6l3 3"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "nodes": '<circle cx="6" cy="12" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M8 12l8-5M8 12l8 5"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 20 3M16 7l3 3M14 9l3 3"/>',
    "log": '<path d="M4 4h16v16H4z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
}


def _svg(name: str, color: str, size: int = 26) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICONS.get(name, "")}</svg>')


def _e(s: Any) -> str:
    return html.escape(str(s))


# --- Global CSS --------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;800&display=swap');

html, body, [class*="css"], .stMarkdown, p, span, div { font-family: 'Archivo', system-ui, sans-serif; }
h1, h2, h3, h4 { font-family: 'Archivo', system-ui, sans-serif; font-weight: 800; color: #0f2a4d; letter-spacing: -0.01em; }
#MainMenu, footer, header [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 2.0rem; max-width: 1240px; }

/* Hero */
.and-hero { border-left: 6px solid #e8732a; padding-left: 18px; margin-bottom: 6px; }
.and-hero h1 { font-size: 2.4rem; margin: 0; }
.and-hero p { color: #5b6b7f; margin: 6px 0 0; font-size: 1.02rem; }

/* Section header */
.and-head { border-left: 5px solid #e8732a; padding-left: 14px; margin: 2px 0 18px; }
.and-head h2 { font-size: 1.7rem; margin: 0; }
.and-head p { color: #5b6b7f; margin: 4px 0 0; font-size: .94rem; }

/* Cards + badges */
.and-card { background:#fff; border:1px solid #e2e9f3; border-radius:14px;
            box-shadow:0 1px 2px rgba(15,42,77,.05); padding:16px; }
.and-badge { font-size:.64rem; font-weight:700; letter-spacing:.05em;
             padding:3px 8px; border-radius:6px; text-transform:uppercase; white-space:nowrap; }
.and-key { font-family: ui-monospace, Menlo, Consolas, monospace; font-size:.72rem;
           color:#2563c9; background:#eef5fd; padding:2px 6px; border-radius:5px; }
.and-id { font-size:.7rem; color:#94a3b8; }

/* Spine (the agent pipeline) */
.and-spine { display:flex; align-items:flex-start; gap:2px; flex-wrap:nowrap;
             justify-content:center; overflow-x:auto; margin:8px 0 14px; }
.and-step { display:flex; flex-direction:column; align-items:center; width:150px; flex:none; text-align:center; }
.and-circle { width:60px; height:60px; border-radius:50%; display:flex;
              align-items:center; justify-content:center; margin-bottom:10px;
              border:3px solid var(--sc); background:var(--bg); }
.and-pill { color:#fff; font-weight:700; font-size:.84rem; padding:5px 14px; border-radius:7px;
            background: var(--pc, #0f2a4d); }
.and-step small { color:#5b6b7f; font-size:.72rem; display:block; margin-top:8px; line-height:1.25; }
.and-step .and-badges { margin-top:9px; display:flex; flex-direction:column; gap:4px; align-items:center; }
.and-arrow { color:#94a3b8; font-size:1.4rem; padding-top:22px; }

/* Legend */
.and-legend { display:inline-flex; flex-wrap:wrap; gap:18px; background:#f6f8fb;
              border:1px solid #eef2f7; border-radius:12px; padding:10px 16px;
              margin:4px 0 14px; font-size:.78rem; color:#5b6b7f; }
.and-legend b { color:#0f2a4d; }
.and-sw { display:inline-flex; align-items:center; gap:6px; }

/* Detail panel */
.and-det { background:#fff; border:1px solid #e2e9f3; border-radius:14px; padding:18px; }
.and-det h3 { margin:.1rem 0 .3rem; font-size:1.25rem; }
.and-detgrid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:8px 0; }
.and-detbox { background:#f6f8fb; border:1px solid #eef2f7; border-radius:9px; padding:7px 10px; }
.and-detbox .k { color:#7a899c; font-size:.6rem; text-transform:uppercase; letter-spacing:.03em; }
.and-detbox .v { color:#0f2a4d; font-weight:700; font-size:.86rem; word-break:break-all; }
.and-detsec { font-weight:800; color:#0f2a4d; margin:14px 0 6px; font-size:.74rem;
              text-transform:uppercase; letter-spacing:.04em; }
.and-detrow { display:flex; justify-content:space-between; gap:12px; padding:5px 0;
              border-bottom:1px solid #f0f3f8; font-size:.82rem; }
.and-detrow .lbl { color:#7a899c; flex:none; }
.and-detrow .val { color:#0f2a4d; text-align:right; word-break:break-all; }
.and-checks { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }

/* Flow row (chain of agent cards) */
.and-flow { display:flex; align-items:stretch; gap:1px; overflow-x:auto; padding:4px 2px 10px; }
.and-fcard { background:#fff; border:1px solid #e2e9f3; border-top:4px solid var(--sc);
             border-radius:10px; padding:11px 13px; width:200px; flex:none; }
.and-fcard .ft { display:flex; justify-content:space-between; align-items:center; gap:8px; }
.and-fcard .fn { font-weight:800; color:#0f2a4d; font-size:.9rem; }
.and-fcard .fs { color:#5b6b7f; font-size:.76rem; margin:3px 0 7px; }
.and-fcard .fr > div { display:flex; justify-content:space-between; padding:2px 0; font-size:.74rem; color:#7a899c; }
.and-fe { display:flex; align-items:center; padding:0 4px; font-size:1.2rem; flex:none; color:#94a3b8; }

/* Event log rows */
.and-ev { display:flex; gap:10px; align-items:flex-start; padding:7px 10px; border-bottom:1px solid #f0f3f8; }
.and-ev .eid { font-family:ui-monospace,Menlo,Consolas,monospace; color:#94a3b8; font-size:.7rem; flex:none; width:54px; }
.and-ev .ebody { flex:1; font-size:.84rem; }
.and-ev .ebody b { color:#0f2a4d; }
</style>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="and-hero"><h1>{_e(title)}</h1>'
        f'{f"<p>{_e(subtitle)}</p>" if subtitle else ""}</div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="and-head"><h2>{_e(title)}</h2>'
        f'{f"<p>{_e(subtitle)}</p>" if subtitle else ""}</div>',
        unsafe_allow_html=True,
    )


def badge(text: str, color: str, bg: str) -> str:
    return f'<span class="and-badge" style="color:{color};background:{bg}">{_e(text)}</span>'


# --- The spine ---------------------------------------------------------------
def spine(states_by_agent: Dict[str, str],
          badges_by_agent: Optional[Dict[str, List[str]]] = None) -> None:
    """Horizontal pipeline of the four agents.

    ``states_by_agent`` maps an agent id to its chain state
    (``acted`` / ``control`` / ``waiting``). ``badges_by_agent`` optionally
    maps an agent id to a list of already-rendered badge HTML strings shown
    under its step (e.g. event count, status).
    """
    badges_by_agent = badges_by_agent or {}
    parts = ['<div class="and-spine">']
    for i, (aid, icon, label, sub) in enumerate(AGENTS):
        state = states_by_agent.get(aid, "waiting")
        sc, bg, _lbl = AGENT_STATE.get(state, (SLATE, GHOST_BG, state))
        pill_bg = "#0f2a4d" if state == "control" else (GREEN if state == "acted" else "#8a98ac")
        bs = badges_by_agent.get(aid, [])
        badges_html = (f'<div class="and-badges">{"".join(bs)}</div>' if bs else "")
        parts.append(
            f'<div class="and-step"><div class="and-circle" style="--sc:{sc};--bg:{bg}">'
            f'{_svg(icon, sc)}</div>'
            f'<div class="and-pill" style="--pc:{pill_bg}">{_e(label)}</div>'
            f'<small>{_e(sub)}</small>{badges_html}</div>'
        )
        if i < len(AGENTS) - 1:
            parts.append('<div class="and-arrow">→</div>')
    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)


# --- Legend ------------------------------------------------------------------
def map_legend() -> None:
    swatches = "".join(
        f'<span class="and-sw"><span style="width:12px;height:12px;border-radius:50px;'
        f'background:{tint};border:3px solid {acc}"></span>{lbl}</span>'
        for _k, _short, _ic, lbl, tint, acc in ARTIFACTS)
    st.markdown(
        '<div class="and-legend">'
        f'<span class="and-sw"><span style="width:13px;height:13px;border-radius:50%'
        f';background:#e7f0fb;border:3px solid {BLUE}"></span>agent (dot)</span>'
        f'<span class="and-sw"><span style="width:13px;height:13px;border-radius:4px;'
        f'background:#dff3f3;border:2px solid {TEAL}"></span>artifact (box)</span>'
        f'<span>&nbsp;|&nbsp;<b>Edges:</b></span>'
        f'<span style="color:{GREEN}">→ writes</span>'
        f'<span style="color:{BLUE}">→ reads (key passed)</span>'
        f'<span style="color:{NAVY}">→ handoff</span>'
        f'<span style="color:{GHOST}">→ pending</span>'
        f'<span>&nbsp;|&nbsp;<b>Fill in:</b> ' + swatches + '</span>'
        '</div>',
        unsafe_allow_html=True,
    )


# --- Detail panels -----------------------------------------------------------
def artifact_detail(key: str, art: Dict[str, Any]) -> None:
    status = art.get("status", "—")
    sc = ARTIFACT_STATUS.get(status, MUTED)
    label = dict((k, lbl) for k, _s, _ic, lbl, _t, _a in ARTIFACTS).get(key, key)
    h = ['<div class="and-det">']
    h.append(
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'{badge(art.get("type","artifact"), MUTED, "#eef2f7")}'
        f'{badge(status, sc, _tint_for_status(status))}</div>'
    )
    h.append(f'<h3>{_e(label)}</h3>')
    h.append(f'<div class="and-id">key: <span class="and-key">{_e(key)}</span></div>')
    h.append('<div class="and-detsec">Content</div><div class="and-detgrid">')
    for k in ("rows", "row_count", "columns", "coerced_cells"):
        if k in art:
            h.append(_cell(k.replace("_", " ").title(), art[k]))
    h.append(_cell("source_hash", (art.get("source_hash", "") or "")[:14] + "…"))
    h.append('</div>')
    # column / field listing
    if "fields" in art:
        h.append('<div class="and-detsec">Schema fields</div>')
        for f in art["fields"]:
            h.append(
                f'<div class="and-detrow"><span class="lbl">{_e(f["name"])}</span>'
                f'<span class="val">{_e(f["type"])}</span></div>'
            )
    if "checks" in art:
        h.append('<div class="and-detsec">Checks</div><div class="and-checks">')
        for ck, cv in art["checks"].items():
            col = GREEN if cv else (AMBER if cv is False else MUTED)
            mark = "✓" if cv else ("✗" if cv is False else "•")
            h.append(badge(f"{mark} {ck}", col, _tint_for_status(
                "ok" if cv else ("warn" if cv is False else "pending"))))
        h.append('</div>')
    if "reasons" in art:
        h.append('<div class="and-detsec">Reasons</div>')
        for r in art["reasons"]:
            h.append(f'<div style="font-size:.82rem;color:#3c4b60;padding:3px 0">• {_e(r)}</div>')
    if art.get("preview_rows"):
        h.append('<div class="and-detsec">Preview (first rows)</div>')
        h.append('<div style="font-size:.74rem;color:#5b6b7f;max-height:140px;overflow:auto">')
        h.append(_e(json_dumps(art["preview_rows"])))
        h.append('</div>')
    h.append('</div>')
    st.markdown("".join(h), unsafe_allow_html=True)


def agent_detail(aid: str, state: str, envelope: Dict[str, Any],
                 events: List[Dict[str, Any]]) -> None:
    label = dict((a, lbl) for a, _ic, lbl, _s in AGENTS).get(aid, aid)
    sc, bg, slbl = AGENT_STATE.get(state, (SLATE, GHOST_BG, state))
    h = ['<div class="and-det">']
    h.append(
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'{badge("agent", NAVY, "#e7f0fb")}'
        f'{badge(slbl, sc, bg)}</div>'
    )
    h.append(f'<h3>{_e(label)}</h3>')
    h.append(f'<div class="and-id">id: <span class="and-key">{_e(aid)}</span></div>')
    if envelope:
        h.append('<div class="and-detsec">Handoff envelope (references, not content)</div>')
        h.append(_cell("from", envelope.get("from_agent", "—")))
        h.append(_cell("to", envelope.get("to_agent", "—")))
        h.append(_cell("handoff_type", envelope.get("handoff_type", "—")))
        h.append(_cell("output_contract", envelope.get("output_contract", "—")))
        h.append('<div class="and-detsec">input_keys (read)</div>')
        for k in envelope.get("input_keys", []):
            h.append(f'<div style="margin:3px 0"><span class="and-key">{_e(k)}</span></div>')
        h.append('<div class="and-detsec">allowed_actions</div><div class="and-checks">')
        for a in envelope.get("allowed_actions", []):
            h.append(badge(a, MUTED, "#eef2f7"))
        h.append('</div>')
    h.append('<div class="and-detsec">Events by this agent</div>')
    aev = [e for e in events if e.get("agent") == aid]
    if aev:
        for e in aev:
            mk = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(e.get("status"), "•")
            h.append(
                f'<div class="and-ev"><span class="eid">{_e(e.get("event_id",""))}</span>'
                f'<span class="ebody">{mk} <b>{_e(e["action"])}</b> '
                f'→ {_e(", ".join(e.get("output_keys",[])) or "—")}'
                f'<br><span style="color:#94a3b8">{_e(e.get("message",""))}</span></span></div>'
            )
    else:
        h.append('<div style="color:#94a3b8;font-size:.82rem">none yet</div>')
    h.append('</div>')
    st.markdown("".join(h), unsafe_allow_html=True)


# --- Flow row (the chain as cards) -------------------------------------------
def chain_flow(chain_status: List[Dict[str, str]], envelopes_by_to: Dict[str, Dict[str, Any]]) -> None:
    """Agent cards connected by handoff arrows."""
    h = ['<div class="and-flow">']
    for i, node in enumerate(chain_status):
        aid = node["agent"]
        state = node["state"]
        sc, bg, slbl = AGENT_STATE.get(state, (SLATE, GHOST_BG, state))
        _icon, label, sub = next((x[1], x[2], x[3]) for x in AGENTS if x[0] == aid)
        env = envelopes_by_to.get(aid, {})
        out = env.get("output_contract", "—")
        h.append(
            f'<div class="and-fcard" style="--sc:{sc}">'
            f'<div class="ft"><span class="fn">{_e(label)}</span>{badge(slbl, sc, bg)}</div>'
            f'<div class="fs">{_e(sub)}</div>'
            f'<div class="fr">'
            f'<div><span>produces</span><b style="color:#0f2a4d">{_e(out)}</b></div>'
            f'<div><span>reads</span><b style="color:#2563c9">{len(env.get("input_keys",[]))} key(s)</b></div>'
            f'</div></div>'
        )
        if i < len(chain_status) - 1:
            h.append('<div class="and-fe">→</div>')
    h.append('</div>')
    st.markdown("".join(h), unsafe_allow_html=True)


# --- Event log ---------------------------------------------------------------
def event_rows(events: List[Dict[str, Any]]) -> None:
    if not events:
        st.info("No events yet — step an agent to grow the audit trail.")
        return
    h = []
    for ev in reversed(events):
        mk = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(ev.get("status"), "•")
        ins = ", ".join(ev.get("input_keys", [])) or "—"
        outs = ", ".join(ev.get("output_keys", [])) or "—"
        checks = ev.get("checks", {})
        ch = "".join(
            badge(k, GREEN if v else (AMBER if v is False else MUTED),
                  _tint_for_status("ok" if v else ("warn" if v is False else "pending")))
            for k, v in checks.items())
        msg = ev.get("message", "")
        msg_span = f'<br><span style="color:#94a3b8">{_e(msg)}</span>' if msg else ""
        checks_span = f'<br>{ch}' if ch else ""
        h.append(
            f'<div class="and-ev"><span class="eid">{_e(ev.get("event_id",""))}</span>'
            f'<span class="ebody">{mk} <b>{_e(ev["agent"])}</b> · {_e(ev["action"])}'
            f'<br><span style="color:#7a899c">in: {_e(ins)} → out: {_e(outs)}</span>'
            f'{checks_span}{msg_span}</span></div>'
        )
    st.markdown("".join(h), unsafe_allow_html=True)


# --- helpers -----------------------------------------------------------------
def _cell(k: str, v: Any) -> str:
    return f'<div class="and-detbox"><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div></div>'


def _tint_for_status(status: str) -> str:
    return {"ok": "#e8f7ee", "pending": "#fdeede", "warn": "#fdeede",
            "error": "#fde8e8"}.get(status, "#eef2f7")


def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)