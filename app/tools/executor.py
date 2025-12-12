from __future__ import annotations

import shutil
import json
from pathlib import Path
from typing import Dict, Any, Tuple

from app.models import ToolPlan, ToolResult
from app.run_context import RunContext
from app.tools.dataset_registry import DatasetRegistry
from app.tools.python_runner import run_python_code


def _schema_check(data: Any, expected: list[str] | None) -> Tuple[bool, list[str], list[str]]:
    if not expected:
        return True, [], []
    errors: list[str] = []
    new_keys: list[str] = []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        sample = data[0]
    elif isinstance(data, dict):
        sample = data
    else:
        errors.append("Preview not in expected structure (dict or list of dicts)")
        return False, errors, new_keys
    for key in sample.keys():
        if key not in expected:
            new_keys.append(key)
    if new_keys:
        errors.append("Unexpected keys: " + ", ".join(new_keys))
    for key in expected:
        if key not in sample:
            errors.append(f"Missing expected key: {key}")
    return not errors, errors, new_keys


def execute_tool_plan(plan: ToolPlan, run_ctx: RunContext, registry: DatasetRegistry) -> ToolResult:
    workspace = registry.prepare_workspace()
    run_ctx.workspace_dir = str(workspace)
    dataset_paths = registry.materialize(workspace)

    merged_artifacts: Dict[str, Any] = {}
    stdout_all = []
    stderr_all = []
    schema_ok = True
    schema_errors: list[str] = []
    new_keys: list[str] = []
    for step in plan.steps:
        if step.kind == "python":
            # Write inputs mapping to a file to simplify user code discovery if needed
            (workspace / "inputs.json").write_text(
                json.dumps({k: str(v) for k, v in dataset_paths.items()}), encoding="utf-8"
            )
            result = run_python_code(step.payload, workspace, plan.limits)
        else:
            return ToolResult(success=False, stderr="SQL runner not implemented in V1", schema_ok=False)

        stdout_all.append(result.stdout or "")
        stderr_all.append(result.stderr or "")
        merged_artifacts.update(result.artifacts)
        if not result.schema_ok:
            schema_ok = False
            schema_errors.extend(result.schema_errors)
            new_keys.extend(result.new_keys)
        if not result.success:
            return ToolResult(
                success=False,
                stdout="\n".join(stdout_all),
                stderr="\n".join(stderr_all),
                metrics=result.metrics,
                artifacts=merged_artifacts,
                schema_ok=schema_ok,
                schema_errors=schema_errors,
                new_keys=new_keys,
            )

        if step.expected_output and "preview" in merged_artifacts:
            ok, errs, extras = _schema_check(merged_artifacts.get("preview", {}), step.expected_output)
            schema_ok = schema_ok and ok
            schema_errors.extend(errs)
            new_keys.extend(extras)

    shutil.rmtree(workspace, ignore_errors=True)
    return ToolResult(
        success=True,
        stdout="\n".join(stdout_all),
        stderr="\n".join(stderr_all),
        metrics={"runtime_ms": None},
        artifacts=merged_artifacts,
        schema_ok=schema_ok,
        schema_errors=schema_errors,
        new_keys=new_keys,
    )
