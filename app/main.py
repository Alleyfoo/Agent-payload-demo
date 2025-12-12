from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.agents.shadow import ShadowAgent
from app.speaker import SpeakerAgent
from app.utils.llm_client import LLMClient

app = FastAPI(title="Moniagenttinen piiriarkkitehtuuri")
speaker: Optional[SpeakerAgent] = None
shadow_agent: Optional[ShadowAgent] = None


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    run_id: str
    decision: str
    summary: str
    content: dict
    shadow_report_path: str


@app.on_event("startup")
async def startup_event() -> None:
    global speaker, shadow_agent
    llm_client = LLMClient()
    shadow_agent = ShadowAgent()
    speaker = SpeakerAgent(llm_client, shadow_agent)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if not speaker:
        raise HTTPException(status_code=500, detail="SpeakerAgent not initialized")
    result = speaker.process_and_summarize(request.message)
    response = result["response"]
    return ChatResponse(**response)


@app.get("/monitor/runs")
async def monitor_runs(limit: int = 20) -> dict:
    if not shadow_agent:
        raise HTTPException(status_code=500, detail="ShadowAgent not initialized")
    history = shadow_agent.get_history(limit if limit > 0 else None)
    return {"runs": history}


@app.get("/monitor/runs/{run_id}")
async def monitor_run(run_id: str) -> dict:
    if not shadow_agent:
        raise HTTPException(status_code=500, detail="ShadowAgent not initialized")
    report = shadow_agent.get_run(run_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return report


@app.get("/monitor/graph")
async def monitor_graph(limit: int = 1) -> dict:
    if not shadow_agent:
        raise HTTPException(status_code=500, detail="ShadowAgent not initialized")
    history = shadow_agent.get_history(limit if limit > 0 else None)
    latest = history[-1] if history else None
    graph = latest.get("graph", {"nodes": [], "edges": []}) if latest else {"nodes": [], "edges": []}
    trace = latest.get("trace", []) if latest else []
    return {
        "latest_run_id": latest.get("run_id") if latest else None,
        "graph": graph,
        "trace": trace,
    }


@app.get("/monitor/dashboard", response_class=HTMLResponse)
async def monitor_dashboard() -> HTMLResponse:
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>Agent Monitor</title>
      <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
      <style>
        :root {
          --bg: #0c0f17;
          --panel: #141a26;
          --accent: #6cf3c5;
          --text: #e4ecf7;
          --muted: #94a3b8;
          --edge: #38bdf8;
        }
        body { margin: 0; font-family: "Space Grotesk", "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
        header { padding: 20px; display: flex; justify-content: space-between; align-items: center; background: #0f1729; border-bottom: 1px solid #1f2937; }
        h1 { margin: 0; font-size: 20px; letter-spacing: 0.05em; }
        main { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; padding: 16px; }
        .card { background: var(--panel); border: 1px solid #1e293b; border-radius: 12px; padding: 12px 14px; box-shadow: 0 10px 30px rgba(0,0,0,0.35); }
        #graph { width: 100%; height: 520px; }
        .trace-table { width: 100%; border-collapse: collapse; }
        .trace-table th, .trace-table td { padding: 6px 8px; border-bottom: 1px solid #1f2937; font-size: 13px; text-align: left; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #1e293b; color: var(--accent); font-size: 11px; }
        button { background: var(--accent); color: #0b0f18; border: none; border-radius: 8px; padding: 8px 12px; font-weight: 600; cursor: pointer; }
      </style>
    </head>
    <body>
      <header>
        <h1>Agent Signal Monitor</h1>
        <button id="refresh">Refresh</button>
      </header>
      <main>
        <section class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <div>
              <div style="font-size:14px;color:var(--muted);">Latest run</div>
              <div id="runId" style="font-size:16px;font-weight:600;">—</div>
            </div>
            <div class="badge" id="edgeCount">0 edges</div>
          </div>
          <svg id="graph"></svg>
        </section>
        <section class="card">
          <div style="font-size:15px;font-weight:600;margin-bottom:6px;">Trace</div>
          <table class="trace-table" id="traceTable">
            <thead>
              <tr><th>Sender → Recipient</th><th>Role</th><th>Timestamp</th></tr>
            </thead>
            <tbody></tbody>
          </table>
        </section>
      </main>
      <script>
        async function loadGraph() {
          const res = await fetch('/monitor/graph');
          const data = await res.json();
          document.getElementById('runId').textContent = data.latest_run_id || '—';
          renderGraph(data.graph || {nodes: [], edges: []});
          renderTrace(data.trace || []);
        }

        function renderTrace(trace) {
          const tbody = document.querySelector('#traceTable tbody');
          tbody.innerHTML = '';
          trace.slice().reverse().forEach(entry => {
            const row = document.createElement('tr');
            const route = document.createElement('td');
            route.textContent = `${entry.sender} → ${entry.recipient}`;
            const role = document.createElement('td');
            role.textContent = entry.role || '';
            const ts = document.createElement('td');
            ts.textContent = entry.timestamp || '';
            row.appendChild(route); row.appendChild(role); row.appendChild(ts);
            tbody.appendChild(row);
          });
        }

        function renderGraph(graph) {
          const svg = d3.select('#graph');
          const width = svg.node().clientWidth;
          const height = svg.node().clientHeight;
          svg.selectAll('*').remove();

          const nodes = graph.nodes.map(n => Object.assign({}, n));
          const links = graph.edges.map(e => Object.assign({}, e));
          document.getElementById('edgeCount').textContent = `${links.length} edges`;

          const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.id).distance(120).strength(0.8))
            .force('charge', d3.forceManyBody().strength(-260))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(50));

          const link = svg.append('g')
            .attr('stroke', 'var(--edge)')
            .attr('stroke-opacity', 0.6)
            .selectAll('line')
            .data(links)
            .enter()
            .append('line')
            .attr('stroke-width', d => 1 + (d.count || 1) * 0.5);

          const node = svg.append('g')
            .attr('stroke', '#0b0f18')
            .attr('stroke-width', 1.5)
            .selectAll('circle')
            .data(nodes)
            .enter()
            .append('circle')
            .attr('r', 18)
            .attr('fill', (_, i) => i === 0 ? 'var(--accent)' : '#38bdf8')
            .call(drag(simulation));

          const labels = svg.append('g')
            .selectAll('text')
            .data(nodes)
            .enter()
            .append('text')
            .text(d => d.id)
            .attr('font-size', 11)
            .attr('fill', '#e5e7eb')
            .attr('text-anchor', 'middle')
            .attr('dy', -24);

          simulation.on('tick', () => {
            link
              .attr('x1', d => d.source.x)
              .attr('y1', d => d.source.y)
              .attr('x2', d => d.target.x)
              .attr('y2', d => d.target.y);
            node
              .attr('cx', d => d.x)
              .attr('cy', d => d.y);
            labels
              .attr('x', d => d.x)
              .attr('y', d => d.y);
          });
        }

        function drag(simulation) {
          function dragstarted(event) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            event.subject.fx = event.subject.x;
            event.subject.fy = event.subject.y;
          }
          function dragged(event) {
            event.subject.fx = event.x;
            event.subject.fy = event.y;
          }
          function dragended(event) {
            if (!event.active) simulation.alphaTarget(0);
            event.subject.fx = null;
            event.subject.fy = null;
          }
          return d3.drag().on('start', dragstarted).on('drag', dragged).on('end', dragended);
        }

        document.getElementById('refresh').addEventListener('click', loadGraph);
        loadGraph();
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
