import json

import pandas as pd

from app.data_pipe.conversation_orchestrator import DataPipeConversationOrchestrator
from app.data_pipe.data_pipe_state import DataPipePhase
from app.data_pipe.data_session_store import DataPipeSessionStore


def test_conversation_flow(tmp_path):
    input_path = tmp_path / "input.xlsx"
    df = pd.DataFrame([{"Name": "Alice", "Amount": 10}, {"Name": "Bob", "Amount": 20}])
    df.to_excel(input_path, index=False)
    output_dir = tmp_path / "out"

    store = DataPipeSessionStore()
    orchestrator = DataPipeConversationOrchestrator(store, allow_root=tmp_path)
    run_id = "test-run-1"

    start_payload = {"action": "start", "input_path": str(input_path), "output_dir": str(output_dir), "preview_rows": 2}
    resp_start = orchestrator.handle(run_id, json.dumps(start_payload))
    assert resp_start["state"]["phase"] == DataPipePhase.HEADERS_PROPOSED_WAITING_CONFIRM.value
    assert resp_start["header_plan"]

    confirm_headers = orchestrator.handle(run_id, json.dumps({"action": "confirm_headers", "run_id": run_id}))
    assert confirm_headers["state"]["phase"] == DataPipePhase.TRANSFORM_PROPOSED_WAITING_CONFIRM.value
    assert confirm_headers["preview_report"]

    confirm_transform = orchestrator.handle(run_id, json.dumps({"action": "confirm_transform", "run_id": run_id}))
    assert confirm_transform["state"]["phase"] == DataPipePhase.DONE.value
    assert confirm_transform["save_report"]["saved_files"]
