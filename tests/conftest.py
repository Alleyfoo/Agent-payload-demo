"""Pytest config: make the package importable from the repo root and give
each test an isolated temp data dir + a fixture-rooted key file.

Tests run from the repo root (`pytest -q`), so the package is on the path as
``agent_network_demo``. The fixture paths are resolved relative to the repo
root, which is what the agents expect.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES = REPO_ROOT / "agent_network_demo" / "fixtures"


@pytest.fixture
def data_dir(tmp_path) -> Path:
    """An isolated per-test directory for the event log JSONL files."""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def key_file_path(data_dir) -> str:
    """Copy the real fixture key file into the temp data dir, rewriting its
    ``source_ref`` to point at the real sample payload on disk."""
    src = FIXTURES / "key_file.json"
    sample = FIXTURES / "sample_payload.json"
    dest = data_dir / "key_file.json"
    payload = json.loads(src.read_text(encoding="utf-8"))
    payload["source_ref"] = str(sample)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(dest)