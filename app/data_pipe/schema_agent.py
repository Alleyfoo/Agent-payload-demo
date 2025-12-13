from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from app.data_pipe.models import ColumnSpec, SchemaSpec


class SchemaAgent:
    def __init__(self, synonyms_path: Path | None = None, version: int = 1, schema_hints_path: Path | None = None) -> None:
        self.synonyms_path = synonyms_path
        self.version = version
        self.schema_hints_path = schema_hints_path
        self.synonyms, self.syn_checksum = self._load_synonyms(synonyms_path)
        self.schema_hints = self._load_hints(schema_hints_path)

    def _load_synonyms(self, path: Path | None) -> Tuple[Dict[str, List[str]], str]:
        if not path or not path.exists():
            return {}, "nosyn"
        data = json.loads(path.read_text(encoding="utf-8"))
        checksum = json.dumps(data, sort_keys=True)
        return data, checksum

    def _load_hints(self, path: Path | None) -> Dict[str, Dict[str, object]]:
        if not path or not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _normalize(name: str) -> str:
        cleaned = name.strip().lower()
        cleaned = re.sub(r"[\\s\\-]+", "_", cleaned)
        cleaned = re.sub(r"[^a-z0-9_]", "", cleaned)
        cleaned = cleaned.strip("_")
        return cleaned

    def _canonical_from_alias(self, normalized: str) -> str:
        for canonical, aliases in self.synonyms.items():
            if normalized == canonical.lower():
                return canonical
            if any(normalized == alias.lower() for alias in aliases):
                return canonical
        return normalized

    def _apply_hints(self, canonical: str) -> Tuple[str, bool]:
        dtype = "string"
        required = False
        if isinstance(self.schema_hints.get("dtype"), dict):
            dtype = str(self.schema_hints["dtype"].get(canonical, dtype))
        if isinstance(self.schema_hints.get("required"), list):
            required = canonical in self.schema_hints["required"]
        return dtype, required

    def build_schema(self, headers: List[str]) -> SchemaSpec:
        cols: List[ColumnSpec] = []
        unmapped: List[str] = []
        seen: Dict[str, int] = {}
        for idx, raw in enumerate(headers):
            base = self._normalize(raw or f"col_{idx}")
            if not base:
                base = f"col_{idx}"
            canonical = self._canonical_from_alias(base)
            count = seen.get(canonical, 0)
            seen[canonical] = count + 1
            if count > 0:
                canonical = f"{canonical}_{count+1}"
            dtype, required = self._apply_hints(canonical)
            cols.append(
                ColumnSpec(
                    raw_name=raw,
                    canonical_name=canonical,
                    dtype=dtype,
                    required=required,
                    notes="",
                )
            )
        canonical_list = [c.canonical_name for c in cols]
        schema_id = SchemaSpec.make_schema_id(canonical_list, self.syn_checksum, self.version)
        return SchemaSpec(
            schema_id=schema_id,
            version=self.version,
            columns=sorted(cols, key=lambda c: c.canonical_name),
            unmapped_columns=unmapped,
            warnings=[],
        )
