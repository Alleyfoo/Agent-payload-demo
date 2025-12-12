from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Dict


class DatasetRegistry:
    """
    Registry for allowed datasets. Maps logical names to source file paths and prepares
    workspace copies for tool execution.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._datasets: Dict[str, Path] = {}
        self.base_dir = base_dir or Path.cwd()

    def register(self, name: str, path: str | Path) -> None:
        p = Path(path)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"Dataset {name} not found at {path}")
        self._datasets[name] = p

    def prepare_workspace(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="toolrun_"))

    def materialize(self, workspace: Path) -> Dict[str, Path]:
        workspace.mkdir(parents=True, exist_ok=True)
        mapping: Dict[str, Path] = {}
        for name, src in self._datasets.items():
            dest = workspace / src.name
            shutil.copy(src, dest)
            mapping[name] = dest
        return mapping
