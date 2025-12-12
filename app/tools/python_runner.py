from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, List

from app.tools.ast_guard import guard_code
from app.models import ToolLimits, ToolResult


def run_python_code(code: str, workspace: Path, limits: ToolLimits) -> ToolResult:
    errors = guard_code(code, limits.allow_imports)
    if errors:
        return ToolResult(success=False, stderr="\n".join(errors), schema_ok=False, schema_errors=errors)

    temp_script = Path(tempfile.mkstemp(prefix="tool_", suffix=".py", dir=workspace)[1])
    temp_script.write_text(code, encoding="utf-8")

    env = {
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    proc = subprocess.run(
        [sys.executable, str(temp_script)],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=limits.timeout_seconds,
        env=env,
    )
    success = proc.returncode == 0
    metrics = {"runtime_ms": None, "peak_mem_mb": None}
    artifacts: Dict[str, Any] = {}
    preview_path = workspace / "preview.json"
    if preview_path.exists():
        try:
            artifacts["preview"] = json.loads(preview_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    output_path = workspace / "output.csv"
    if output_path.exists():
        artifacts["output_csv_path"] = str(output_path)
    return ToolResult(
        success=success,
        stdout=proc.stdout,
        stderr=proc.stderr,
        metrics=metrics,
        artifacts=artifacts,
        schema_ok=True,
        schema_errors=[],
        new_keys=[],
    )
