import json
from pathlib import Path

from app.models import ToolPlan, ToolStep, ToolLimits
from app.run_context import RunContext
from app.tools.dataset_registry import DatasetRegistry
from app.tools.executor import execute_tool_plan


def test_tool_executor_python_pipeline(tmp_path: Path):
    # prepare dataset
    csv_path = tmp_path / "input.csv"
    csv_path.write_text("a,b\n1,3\n2,4\n", encoding="utf-8")
    registry = DatasetRegistry()
    registry.register("input_csv", csv_path)

    code = """
import csv, json
rows = []
with open("input.csv") as f:
    rdr = csv.DictReader(f)
    for row in rdr:
        row["sum"] = int(row["a"]) + int(row["b"])
        rows.append(row)
with open("output.csv","w",newline="") as f:
    w = csv.DictWriter(f, fieldnames=["a","b","sum"])
    w.writeheader(); w.writerows(rows)
with open("preview.json","w") as f:
    json.dump(rows[:1], f)
"""
    plan = ToolPlan(
        steps=[
            ToolStep(
                step_id="s1",
                kind="python",
                payload=code,
                expected_output=["a", "b", "sum"],
                output_artifact_key="output_csv_path",
            )
        ],
        limits=ToolLimits(timeout_seconds=5),
    )

    run_ctx = RunContext()
    result = execute_tool_plan(plan, run_ctx, registry)
    assert result.success is True
    assert result.schema_ok is True
    assert "output_csv_path" in result.artifacts
    preview = result.artifacts.get("preview")
    assert isinstance(preview, list) and preview
    assert set(preview[0].keys()) == {"a", "b", "sum"}
