from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict

from app.agents.shadow import ShadowAgent
from app.data_pipe.models import SchemaSpec
from app.data_pipe.save_agent import SaveAgent
from app.data_pipe.schema_agent import SchemaAgent
from app.data_pipe.transform_agent import TransformAgent
from app.models import EnergyVector
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
    support: dict | None = None


class EnergyInput(BaseModel):
    tension: float | None = None
    entropy: float | None = None
    polarity: float | None = None
    coherence: float | None = None


class HybridChatRequest(BaseModel):
    message: str
    energy: EnergyInput | None = None
    hexagram_id: int | None = None
    task_type: str | None = None


class HeaderChatRequest(BaseModel):
    headers: list[str]
    schema_hints_path: str | None = None


class SchemaChatRequest(BaseModel):
    headers: list[str]
    schema_hints_path: str | None = None


class TransformChatRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    schema: dict
    rows: list[dict]


class SaveChatRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    schema: dict
    rows: list[dict]
    output_dir: str
    overwrite: bool | None = False


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


@app.post("/chat/hybrid")
async def chat_hybrid(request: HybridChatRequest):
    if not speaker:
        raise HTTPException(status_code=500, detail="SpeakerAgent not initialized")

    energy = None
    if request.energy:
        energy = EnergyVector(
            tension=request.energy.tension or 0.5,
            entropy=request.energy.entropy or 0.5,
            polarity=request.energy.polarity or 0.0,
            coherence=request.energy.coherence or 0.5,
        )

    result = speaker.process_hierarchical(
        request.message,
        energy=energy,
        hexagram_id=request.hexagram_id,
        task_type=request.task_type,
    )
    if isinstance(result, str):
        return Response(content=result, media_type="application/json")
    return result


@app.post("/chat/header_agent")
async def chat_header_agent(request: HeaderChatRequest) -> dict:
    agent = SchemaAgent(schema_hints_path=Path(request.schema_hints_path) if request.schema_hints_path else None)
    schema = agent.build_schema(request.headers)
    rename_map = {c.raw_name: c.canonical_name for c in schema.columns}
    summary = f"Nimet normalisoitu: {len(rename_map)} saraketta. Unmapped: {len(schema.unmapped_columns)}."
    return {"rename_map": rename_map, "schema": schema.model_dump(), "summary": summary}


@app.post("/chat/schema_agent")
async def chat_schema_agent(request: SchemaChatRequest) -> dict:
    agent = SchemaAgent(schema_hints_path=Path(request.schema_hints_path) if request.schema_hints_path else None)
    schema = agent.build_schema(request.headers)
    summary = f"Schema v{schema.version}: {len(schema.columns)} saraketta, warnings: {len(schema.warnings)}."
    return {"schema": schema.model_dump(), "summary": summary}


@app.post("/chat/transform_agent")
async def chat_transform_agent(request: TransformChatRequest) -> dict:
    schema = SchemaSpec.model_validate(request.schema)
    df = pd.DataFrame(request.rows)
    agent = TransformAgent()
    df_out, report = agent.apply(df, schema)
    sample = df_out.head(5).to_dict(orient="records")
    return {"transform_report": report.model_dump(), "sample_rows": sample}


@app.post("/chat/save_agent")
async def chat_save_agent(request: SaveChatRequest) -> dict:
    schema = SchemaSpec.model_validate(request.schema)
    df = pd.DataFrame(request.rows)
    transform_agent = TransformAgent()
    df_out, report = transform_agent.apply(df, schema)
    run_id = str(uuid.uuid4())
    from app.data_pipe.models import RunResult, SaveReport

    provisional = RunResult(
        run_id=run_id,
        schema=schema,
        transform=report,
        save=SaveReport(saved_files=[], output_dir=request.output_dir),
        chat_summary="",
    )
    save_agent = SaveAgent(allow_root=Path(request.output_dir))
    save_report = save_agent.save(df_out, provisional, Path(request.output_dir))
    summary = f"Run {run_id}: tallennus {'onnistui' if save_report.saved_files else 'ei tallentanut'}; kohde {save_report.output_dir}."
    return {
        "run_id": run_id,
        "transform_report": report.model_dump(),
        "save_report": save_report.model_dump(),
        "summary": summary,
    }


@app.post("/chat/inspect_headers")
async def chat_inspect_headers(file: UploadFile = File(...)) -> dict:
    filename = file.filename or ""
    content = await file.read()
    try:
        if filename.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(BytesIO(content), nrows=1)
        else:
            df = pd.read_csv(BytesIO(content), nrows=1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {exc}") from exc
    return {"filename": filename, "columns": list(df.columns)}


@app.get("/puhemies", response_class=HTMLResponse)
async def puhemies_chat() -> HTMLResponse:
    html = """
    <!DOCTYPE html>
    <html lang="fi">
    <head>
      <meta charset="UTF-8" />
      <title>Puhemies ja agentit</title>
        <style>
        body { font-family: "Segoe UI", sans-serif; margin: 0; background: #0f1729; color: #e5e7eb; }
        main { max-width: 1100px; margin: 24px auto; padding: 20px; background: #111827; border: 1px solid #1f2937; border-radius: 12px; }
        h1 { margin-top: 0; }
        label { display: block; margin-bottom: 4px; color: #94a3b8; }
        textarea { width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #1f2937; background: #0b1220; color: #e5e7eb; }
        select, input[type="text"] { width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #1f2937; background: #0b1220; color: #e5e7eb; }
        button { background: #6cf3c5; color: #0b0f18; border: none; border-radius: 8px; padding: 10px 16px; font-weight: 600; cursor: pointer; margin-top: 10px; }
        .panel { margin-top: 16px; padding: 12px; border-radius: 10px; border: 1px solid #1f2937; background: #0b1220; }
        .label { color: #94a3b8; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; }
        pre { white-space: pre-wrap; max-height: 220px; overflow-y: auto; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
        .hint { font-size: 12px; color: #94a3b8; margin-top: 4px; }
      </style>
    </head>
    <body>
      <main>
        <h1>Puhemies & agentit</h1>

        <div class="panel">
          <div class="label">Puhemies</div>
          <label for="message">Viesti</label>
          <textarea id="message" rows="3" placeholder="Kysy puhemiehelta tai syötä JSON data-agenteille..."></textarea>
          <div style="margin-top:8px;">
            <label for="taskType">Task type (optional override)</label>
            <select id="taskType">
              <option value="">Auto</option>
              <option value="general_help">general_help</option>
              <option value="weather_lookup">weather_lookup</option>
              <option value="debugging">debugging</option>
              <option value="data_extraction">data_extraction</option>
              <option value="data_pipeline_design">data_pipeline_design</option>
              <option value="agentic">agentic</option>
              <option value="policy_update">policy_update</option>
              <option value="math">math</option>
            </select>
          </div>
          <div style="margin-top:8px;">
            <label for="targetAgent">Kohde-agentti</label>
            <select id="targetAgent">
              <option value="speaker">Puhemies (default)</option>
              <option value="header">Header Agent</option>
              <option value="schema">Schema Agent</option>
              <option value="transform">Transform Agent</option>
              <option value="save">Save Agent</option>
            </select>
            <p class="hint">Puhemies tunnistaa automaattisesti avainsanoja (header/schema/transform/save) ja ohjaa puheen oikealle agentille.</p>
          </div>
          <button id="send">Lähetä Puhemiehelle</button>
          <div style="margin-top:8px; display:flex; align-items:center; gap:8px;">
            <span class="label" style="margin:0;">Data pipe run_id</span>
            <code id="data-pipe-run-id">-</code>
            <button type="button" onclick="clearDataPipeRunId()" style="margin-top:0;">Reset</button>
          </div>
          <p class="hint">run_id tallennetaan automaattisesti data pipe -vastauksista ja liitetään seuraavaan viestiin.</p>
          <pre id="response">-</pre>
        </div>

        <div class="grid">
          <div class="panel">
            <div class="label">Header Agent</div>
            <textarea id="header-input" placeholder='JSON esim: {"headers":["Name","Amount"]}'></textarea>
            <div style="margin-top:6px;">
              <input type="file" id="header-file" accept=".xls,.xlsx,.csv" />
              <button onclick="readHeaderFile()">Lue tiedoston header</button>
            </div>
            <button onclick="sendHeader()">Lähetä Header-pyyntö</button>
            <pre id="header-output">-</pre>
          </div>
          <div class="panel">
            <div class="label">Schema Agent</div>
            <textarea id="schema-input" placeholder='JSON esim: {"headers":["Name","Amount"]}'></textarea>
            <button onclick="sendSchema()">Lähetä Schema-pyyntö</button>
            <pre id="schema-output">-</pre>
          </div>
          <div class="panel">
            <div class="label">Transform Agent</div>
            <textarea id="transform-input" placeholder='JSON esim: {"schema":{...},"rows":[{"Name":"Alice","Amount":10}]}'></textarea>
            <button onclick="sendTransform()">Lähetä Transform-pyyntö</button>
            <pre id="transform-output">-</pre>
          </div>
          <div class="panel">
            <div class="label">Save Agent</div>
            <textarea id="save-input" placeholder='JSON esim: {"schema":{...},"rows":[...],"output_dir":"/tmp/out","overwrite":false}'></textarea>
            <button onclick="sendSave()">Tallenna</button>
            <pre id="save-output">-</pre>
          </div>
        </div>
      </main>
      <script>
        const agentDetectionRules = [
          { target: 'header', keywords: ['header', 'headers', 'otsikko', 'sarake', 'column names', 'normalize headers'] },
          { target: 'schema', keywords: ['schema', 'scheman', 'rakenne', 'structure', 'schema agent'] },
          { target: 'transform', keywords: ['transform', 'convert', 'muunna', 'muunnos', 'transform agent', 'normalize'] },
          { target: 'save', keywords: ['save', 'export', 'output_dir', 'tallenna', 'write file', 'output file'] },
        ];
        const dataPipeRunIdKey = 'dataPipeRunId';

        function detectTargetAgent(message) {
          const normalized = (message || '').toLowerCase();
          for (const rule of agentDetectionRules) {
            if (rule.keywords.some((keyword) => normalized.includes(keyword))) {
              return rule.target;
            }
          }
          return null;
        }

        function getStoredRunId() {
          try {
            return localStorage.getItem(dataPipeRunIdKey) || '';
          } catch (e) {
            return '';
          }
        }

        function setStoredRunId(runId) {
          const safeId = runId || '';
          try {
            if (safeId) {
              localStorage.setItem(dataPipeRunIdKey, safeId);
            } else {
              localStorage.removeItem(dataPipeRunIdKey);
            }
          } catch (e) {
            // ignore storage issues
          }
          const node = document.getElementById('data-pipe-run-id');
          if (node) {
            node.textContent = safeId || '-';
          }
        }

        function clearDataPipeRunId() {
          setStoredRunId('');
        }

        // init display from storage
        setStoredRunId(getStoredRunId());

        function updateAgentPanel(target, data) {
          const panel = document.getElementById(`${target}-output`);
          if (!panel) {
            return;
          }
          panel.textContent = JSON.stringify(data, null, 2);
          panel.scrollTop = panel.scrollHeight;
        }

        async function send() {
          const msg = document.getElementById('message').value.trim();
          if (!msg) return;
          const taskType = document.getElementById('taskType').value;
          const manualTarget = document.getElementById('targetAgent').value || 'speaker';
          let target = manualTarget;
          if (manualTarget === 'speaker') {
            const autoTarget = detectTargetAgent(msg);
            if (autoTarget) {
              target = autoTarget;
            }
          }
          const agentLabel = manualTarget === 'speaker' && target !== manualTarget ? `${manualTarget} -> ${target}` : target;
          let endpoint = '/chat/hybrid';
          let payload = {};
          if (target === 'speaker') {
            let messageBody = msg;
            try {
              const maybeJson = JSON.parse(msg);
              if (maybeJson && typeof maybeJson === 'object' && maybeJson.action) {
                if (!maybeJson.run_id) {
                  const storedId = getStoredRunId();
                  if (storedId) {
                    maybeJson.run_id = storedId;
                  }
                }
                messageBody = JSON.stringify(maybeJson);
              }
            } catch (e) {
              // ignore parse errors, treat as plain text
            }
            payload = { message: messageBody, task_type: taskType || null };
          } else {
            // Data-agentit: try JSON parsing, otherwise fall back to a simple payload
            try {
              payload = JSON.parse(msg);
            } catch (e) {
              if (target === 'header' || target === 'schema') {
                payload = { headers: [msg] }; // fallback: treat input as a header name
              } else {
                payload = { message: msg };
              }
            }
          }
          if (target === 'speaker') {
            endpoint = '/chat/hybrid';
          } else if (target === 'header') {
            endpoint = '/chat/header_agent';
          } else if (target === 'schema') {
            endpoint = '/chat/schema_agent';
          } else if (target === 'transform') {
            endpoint = '/chat/transform_agent';
          } else if (target === 'save') {
            endpoint = '/chat/save_agent';
          }

          const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const errText = await res.text();
            document.getElementById('response').textContent = 'Error ' + res.status + ': ' + errText;
            return;
          }
          const data = await res.json();
          const responseNode = document.getElementById('response');
          responseNode.textContent = `Agent: ${agentLabel}\n${JSON.stringify(data, null, 2)}`;
          responseNode.scrollTop = responseNode.scrollHeight;
          if (data && data.state && data.state.run_id && (data.header_plan || (data.state.phase && data.state.phase.toString().toLowerCase().includes('head')) || data.output_path)) {
            setStoredRunId(data.state.run_id);
          }
          updateAgentPanel(target, data);
        }
        document.getElementById('send').addEventListener('click', send);
        document.getElementById('message').addEventListener('keydown', (e) => {
          if (e.ctrlKey && e.key === 'Enter') send();
        });

        async function sendHeader(payloadOverride) {
          let payload = payloadOverride;
          if (!payload) {
            const text = document.getElementById('header-input').value;
            try {
              payload = JSON.parse(text);
            } catch (e) {
              document.getElementById('header-output').textContent = 'Virhe: ' + e;
              return;
            }
          }
          const res = await fetch('/chat/header_agent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (!res.ok) {
            const errText = await res.text();
            document.getElementById('header-output').textContent = 'Virhe: ' + res.status + ': ' + errText;
            return;
          }
          const data = await res.json();
          updateAgentPanel('header', data);
          const headerOutput = document.getElementById('header-output');
          headerOutput.textContent = JSON.stringify(data, null, 2);
          headerOutput.scrollTop = headerOutput.scrollHeight;
          const responseNode = document.getElementById('response');
          responseNode.textContent = `Agent: header\n${JSON.stringify(data, null, 2)}`;
          responseNode.scrollTop = responseNode.scrollHeight;
        }

        async function readHeaderFile() {
          const fileInput = document.getElementById('header-file');
          if (!fileInput.files || !fileInput.files[0]) {
            document.getElementById('header-output').textContent = 'Valitse tiedosto ensin.';
            return;
          }
          const formData = new FormData();
          formData.append('file', fileInput.files[0]);
          try {
            const res = await fetch('/chat/inspect_headers', {
              method: 'POST',
              body: formData,
            });
            const out = document.getElementById('header-output');
            if (!res.ok) {
              const txt = await res.text();
              out.textContent = 'Virhe: ' + res.status + ' ' + txt;
              return;
            }
            const data = await res.json();
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
            const payload = { headers: data.columns };
            document.getElementById('header-input').value = JSON.stringify(payload, null, 2);
            await sendHeader(payload);
          } catch (e) {
            document.getElementById('header-output').textContent = 'Virhe: ' + e;
          }
        }

        async function sendSchema() {
          const text = document.getElementById('schema-input').value;
          try {
            const payload = JSON.parse(text);
            const res = await fetch('/chat/schema_agent', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload),
            });
            const data = await res.json();
            const out = document.getElementById('schema-output');
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
          } catch (e) {
            document.getElementById('schema-output').textContent = 'Virhe: ' + e;
          }
        }

        async function sendTransform() {
          const text = document.getElementById('transform-input').value;
          try {
            const payload = JSON.parse(text);
            const res = await fetch('/chat/transform_agent', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload),
            });
            const data = await res.json();
            const out = document.getElementById('transform-output');
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
          } catch (e) {
            document.getElementById('transform-output').textContent = 'Virhe: ' + e;
          }
        }

        async function sendSave() {
          const text = document.getElementById('save-input').value;
          try {
            const payload = JSON.parse(text);
            const res = await fetch('/chat/save_agent', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload),
            });
            const data = await res.json();
            const out = document.getElementById('save-output');
            out.textContent = JSON.stringify(data, null, 2);
            out.scrollTop = out.scrollHeight;
          } catch (e) {
            document.getElementById('save-output').textContent = 'Virhe: ' + e;
          }
        }
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
