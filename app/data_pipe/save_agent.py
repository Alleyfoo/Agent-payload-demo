from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

import pandas as pd

from app.data_pipe.models import RunResult, SaveReport


def _default_allow_root() -> Path:
    env_root = os.getenv("DATA_PIPE_ALLOW_ROOT")
    if env_root:
        try:
            return Path(env_root).resolve()
        except Exception:
            pass
    fallback = Path("/mnt/data")
    if fallback.exists():
        return fallback.resolve()
    return Path.cwd().resolve()


class SaveAgent:
    def __init__(self, allow_root: Path | None = None) -> None:
        self.allow_root = (allow_root or _default_allow_root()).resolve()

    def _guard_path(self, output_dir: Path) -> Path | None:
        try:
            resolved = output_dir.resolve()
        except Exception:
            return None
        if not str(resolved).startswith(str(self.allow_root)):
            return None
        return resolved

    def save(self, df: pd.DataFrame, run_result: RunResult, output_dir: Path) -> SaveReport:
        guard = self._guard_path(output_dir)
        if guard is None:
            return SaveReport(saved_files=[], output_dir=str(output_dir))
        run_dir = guard / f"run_{run_result.run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        saved: List[str] = []
        data_path = run_dir / "data_canonical.xlsx"
        df.to_excel(data_path, index=False)
        saved.append(str(data_path))

        (run_dir / "SchemaSpec.json").write_text(json.dumps(run_result.schema.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        saved.append(str(run_dir / "SchemaSpec.json"))
        (run_dir / "TransformReport.json").write_text(json.dumps(run_result.transform.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        saved.append(str(run_dir / "TransformReport.json"))
        summary_payload = run_result.model_dump()
        # strip potential large dataframe references (none present)
        (run_dir / "RunSummary.json").write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        saved.append(str(run_dir / "RunSummary.json"))

        return SaveReport(saved_files=saved, output_dir=str(run_dir))
