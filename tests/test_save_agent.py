from pathlib import Path

import pandas as pd

from app.data_pipe.models import RunResult, SaveReport, SchemaSpec, TransformReport, ColumnSpec
from app.data_pipe.save_agent import SaveAgent


def _dummy_run_result(run_id: str, output_dir: str) -> RunResult:
    schema = SchemaSpec(
        schema_id="s1",
        version=1,
        columns=[ColumnSpec(raw_name="A", canonical_name="a", dtype="int", required=False, notes="")],
        unmapped_columns=[],
        warnings=[],
    )
    transform = TransformReport(rows_in=1, rows_out=1, casts_failed={}, missing_required=[], warnings=[])
    save = SaveReport(saved_files=[], output_dir=output_dir)
    return RunResult(run_id=run_id, schema=schema, transform=transform, save=save, chat_summary="")


def test_save_agent_writes_all_reports(tmp_path):
    df = pd.DataFrame([{"a": 1}])
    run_result = _dummy_run_result("r1", str(tmp_path))
    agent = SaveAgent(allow_root=tmp_path)
    report = agent.save(df, run_result, tmp_path)
    assert report.saved_files
    for path in report.saved_files:
        assert Path(path).exists()
