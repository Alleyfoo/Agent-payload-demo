# Agents pass keys, not blobs

A small, deterministic, in-process architecture demo. Agents exchange artifact
keys rather than payload content. A trusted runner constructs every
runner-enforced scoped handoff, grants a capability-scoped store view, validates
actual reads and writes, and records an authorization receipt after each stage.

This is deliberately free of LLM, network, database, and distributed-execution
dependencies. It demonstrates an architecture, not a cryptographic security
boundary.

```
Key file (intent + bounded source selection)
  -> trusted runner grants IntakeAgent
  -> trusted runner grants SchemaAgent
  -> trusted runner grants TransformAgent
  -> trusted runner grants ValidationAgent
  -> human-readable verdict
```

## How the boundary works

- `ArtifactStore` owns immutable artifacts. Public reads and snapshots return
  deep copies, and snapshot hydration verifies every `source_hash`.
- `StoreView` permits only the runner-granted input keys and one contracted
  output key. It records actual reads and writes for the runner receipt.
- `IntakeAgent` is the only component in the agent chain that opens the source
  file. It stores the complete rows at `artifact.raw_input`; UI panels show only
  a preview.
- Schema and Transform read complete source content from granted artifacts.
  They never receive or reopen a filesystem path as operational input.
- Agents return output keys, a summary, and operational details. They do not
  construct the next permission-bearing envelope.
- `WORKFLOW_ROUTES` in `demo_runner.py` fixes each receiving agent, input grant,
  output contract, allowed action, and next stage. Key-file action fields cannot
  grant runtime permissions.
- The JSONL event log is append-only through the application API. It is not
  described as tamper-proof or tamper-evident.
- UUID-based run IDs avoid collisions between concurrent or deleted runs.

## What this demo proves

- Handoffs carry keys rather than artifact content.
- Runtime grants restrict reads and writes.
- Only Intake accesses the source file.
- Agents cannot choose their successors' permissions.
- Artifact mutation outside a contracted write is blocked.
- A final ValidationAgent checks the artifact chain and runner-owned receipts.

## What this demo does not prove

- Security between separate processes or machines.
- Cryptographic identity or authorization.
- LLM reliability.
- Lower token usage at production scale.
- Self-healing or adaptive retry.
- Protection against a compromised trusted runner.

## Handoff example

```json
{
  "run_id": "run_7e2a...",
  "from_agent": "intake_agent",
  "to_agent": "schema_agent",
  "handoff_type": "schema_request",
  "input_keys": ["artifact.raw_input"],
  "output_contract": "schema_profile.v1",
  "context_summary": "Loaded 20 source rows.",
  "allowed_actions": ["read_artifact", "write_schema_profile"]
}
```

The envelope contains a key and summary, not table rows. The complete raw rows
remain in the artifact store.

## Project layout

```
agent_network_demo/
  streamlit_app.py      # Streamlit click-through UI
  demo_runner.py        # trusted route table, envelopes, grants, receipts
  agents.py             # deterministic Intake/Schema/Transform/Validation
  contracts.py          # closed actions and output contracts
  artifact_store.py     # immutable store and scoped StoreView
  event_log.py          # application-API append-only JSONL log
  fixtures/             # bounded key file and sample payloads
tests/                  # unit, end-to-end, smoke, and adversarial tests
```

## Run

```bash
pip install -r requirements.txt
pytest -q
streamlit run agent_network_demo/streamlit_app.py
```

In the UI, click **Start run**, then **Step next agent** four times. Each step
adds the agent's work event and the trusted runner's authorization receipt. The
fourth step runs ValidationAgent and displays the final verdict.

## Artifact keys

- `artifact.raw_input`
- `artifact.schema_profile`
- `artifact.cleaned_output`
- `artifact.validation_verdict`
