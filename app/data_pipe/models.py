from __future__ import annotations

import hashlib
import json
from typing import Dict, List

from pydantic import BaseModel, Field, ConfigDict


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    raw_name: str
    canonical_name: str
    dtype: str
    required: bool = False
    notes: str = ""


class SchemaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    schema_id: str
    version: int
    columns: List[ColumnSpec] = Field(default_factory=list)
    unmapped_columns: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @staticmethod
    def make_schema_id(canonical_names: List[str], synonyms_checksum: str, version: int) -> str:
        payload = {
            "canonical": canonical_names,
            "synonyms": synonyms_checksum,
            "version": version,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return digest


class TransformReport(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    rows_in: int
    rows_out: int
    casts_failed: Dict[str, int] = Field(default_factory=dict)
    missing_required: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class SaveReport(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    saved_files: List[str]
    output_dir: str


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    run_id: str
    schema: SchemaSpec
    transform: TransformReport
    save: SaveReport
    chat_summary: str
