from pathlib import Path

from app.models import ToolLimits
from app.tools.python_runner import run_python_code


def test_python_runner_blocks_os_import(tmp_path: Path):
    code = "import os\nprint(os.listdir())"
    limits = ToolLimits(timeout_seconds=5)
    result = run_python_code(code, tmp_path, limits)
    assert result.success is False
    assert "Import not allowed" in (result.stderr or "")


def test_python_runner_allows_pandas_and_writes_preview(tmp_path: Path):
    code = """
import csv, json
rows = [{"a":1,"b":3},{"a":2,"b":4}]
with open("output.csv","w",newline="") as f:
    w = csv.DictWriter(f, fieldnames=["a","b"])
    w.writeheader()
    w.writerows(rows)
with open("preview.json","w") as f:
    json.dump(rows[:1], f)
print("ok")
"""
    limits = ToolLimits(timeout_seconds=5)
    result = run_python_code(code, tmp_path, limits)
    assert result.success is True
    assert result.artifacts.get("output_csv_path")
    assert isinstance(result.artifacts.get("preview"), list)
