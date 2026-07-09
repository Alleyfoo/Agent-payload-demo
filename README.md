# Agents pass keys, not blobs

A small, deterministic multi-agent demo where the central idea is: **agents
hand each other *references* into a shared artifact store — never the content
itself.** An append-only event log records who did what, with which input and
output keys. v1 uses deterministic mock agents — no LLM, no network. The
architecture is the point.

```
Key file
  ↓
IntakeAgent        → writes artifact + event
  ↓
SchemaAgent        → writes schema + event
  ↓
TransformAgent     → writes transformed output + event
  ↓
ValidationAgent / ShadowJudge → writes verdict + event
Human inspects the whole chain
```

Three things grow at once, visually:

1. **Agent chain** — who has control now, who already acted, who is waiting.
2. **Shared state** — a registry of named artifacts (NOT one giant chat context).
3. **Event log** — append-only JSONL: who did what, with what input key, what
   output key, what validation result.

## The trick: agents pass keys, not blobs

The handoff envelope (the message between agents) carries **references**, not
content:

```json
{
  "run_id": "run_001",
  "from_agent": "intake_agent",
  "to_agent": "schema_agent",
  "handoff_type": "schema_request",
  "input_keys": ["artifact.raw_input"],
  "output_contract": "schema_profile.v1",
  "context_summary": "Uploaded order file needs schema inference.",
  "allowed_actions": ["read_artifact", "write_schema_profile"]
}
```

The shared state holds the content by key:

```json
{
  "artifact.raw_input": {
    "type": "table_preview",
    "rows": 20,
    "columns": ["Order ID", "Customer", "Date", "Total"],
    "source_hash": "b8f3..."
  }
}
```

The event log grows:

```json
{
  "event_id": "evt_003",
  "run_id": "run_001",
  "agent": "schema_agent",
  "action": "write_artifact",
  "input_keys": ["artifact.raw_input"],
  "output_keys": ["artifact.schema_profile"],
  "status": "ok",
  "checks": { "schema_valid": true, "allowed_write": true },
  "timestamp": "2026-07-09T07:12:44+00:00"
}
```

Context stays manageable because agents carry references, not the whole
world.

## Project layout

```
agent_network_demo/
  streamlit_app.py      # Streamlit UI
  demo_runner.py        # Steps agents one at a time; owns the RunSession
  agents.py             # IntakeAgent, SchemaAgent, TransformAgent,
                        #   ValidationAgent (ShadowJudge) — deterministic mocks
  contracts.py          # HandoffEnvelope; allowed_actions; output_contract constants
  event_log.py          # Append-only JSONL writer; Event dataclass; read-back
  artifact_store.py     # ArtifactStore: register/get by key; source_hash
  fixtures/
    key_file.json       # starting permission / task pointer
    sample_payload.json # sample tabular payload (20 orders)
tests/
  test_artifact_store.py
  test_event_log.py
  test_contracts.py
  test_demo_runner.py
  test_agents.py
requirements.txt         # streamlit, pytest (dev)
```

## Module behaviors

- **`artifact_store.py`** — `ArtifactStore` (in-memory, snapshots to JSON).
  `register(key, artifact)` stamps a `source_hash` (sha256 of canonical JSON).
  Re-registering the same content is idempotent; re-registering *different*
  content under an existing key raises `DuplicateKeyError`. `get`, `keys`,
  `as_dict`, `summary` for the UI.
- **`event_log.py`** — `EventLog.append(event)` assigns `evt_NNN` + an
  ISO-8601 timestamp, writes a JSONL line to `data/events_{run_id}.jsonl`,
  and keeps an in-memory list. `for_run` / `all` / `as_dicts` for read-back.
- **`contracts.py`** — `HandoffEnvelope` dataclass. `validate_inbound(store)`
  checks every declared `input_key` exists before an agent runs;
  `validate_outbound(output_keys)` checks that the keys an agent wrote match
  its declared `output_contract`. `ALLOWED_ACTIONS` and `OUTPUT_CONTRACTS`
  are closed sets — an agent's powers are declared on the envelope, not
  invented at runtime.
- **`agents.py`** — four deterministic mock agents, each
  `run(envelope, store, log) -> HandoffEnvelope`. No LLM, no network.
  - `IntakeAgent`: loads the key file's payload, writes `artifact.raw_input`.
  - `SchemaAgent`: infers column→type, writes `artifact.schema_profile`.
  - `TransformAgent`: coerces/normalizes the table, writes `artifact.cleaned_output`.
  - `ValidationAgent` (ShadowJudge): independently re-reads the chain's
    artifacts + event log, writes `artifact.validation_verdict` (ok/warn + reasons).
- **`demo_runner.py`** — `RunSession`: `start_run(key_file)` creates a `run_id`,
  seeds the store + log, builds the ordered agent list; `step()` runs the
  current agent, validates the contract in/out, advances, returns a snapshot;
  `reset()` clears the run. Exposes `chain_status`, `state`, `events`,
  `report`.

## Run

```bash
pip install -r requirements.txt

# tests
pytest -q

# the demo UI
streamlit run agent_network_demo/streamlit_app.py
```

### Killer demo (the click sequence)

1. Load `agent_network_demo/fixtures/key_file.json` (the default).
2. Click **▶ Start run**.
3. Click **⏭ Step next agent** → IntakeAgent writes
   `artifact.raw_input`; event log +1 row.
4. Step again → SchemaAgent writes `artifact.schema_profile`; event log +1.
5. Step again → TransformAgent writes `artifact.cleaned_output`; event log +1.
6. Step again → the ShadowJudge validates the chain, writes
   `artifact.validation_verdict`; the **Final report** tab fills in.

## Artifact key scheme

Used everywhere (fixtures, agents, tests):

- `artifact.raw_input`
- `artifact.schema_profile`
- `artifact.cleaned_output`
- `artifact.validation_verdict`

## Future / out of scope

- LLM-backed agents (Ollama) as a toggle — v1 is deliberately deterministic.
- Persisting runs across restarts (snapshot store + log to disk).
- More agents / branching chains.

## Glossary

- **Key file** — starting permission / task pointer.
- **Handoff envelope** — the message between agents (keys + a summary, not content).
- **Artifact store** — shared memory by key.
- **Event log** — append-only audit trail.
- **Shadow judge** — independent reviewer (`ValidationAgent`).
- **Run report** — human-readable final receipt.