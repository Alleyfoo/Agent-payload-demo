from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


DEFAULT_TOKEN_MAP: Dict[str, Dict[str, str]] = {
    "zp": {"coating": "zinc plated"},
    "zn": {"coating": "zinc plated"},
    "zinc": {"coating": "zinc plated"},
    "a2": {"material": "stainless A2"},
    "a4": {"material": "stainless A4"},
    "8.8": {"grade": "8.8"},
    "4.6": {"grade": "4.6"},
}


@dataclass
class PatchResult:
    updated_artifact: Optional[Any]
    rendered: str
    notes: List[str]


class PatchResolverCircuit:
    """
    Applies simple patch/update instructions to the latest artifact.
    Focuses on fastener token normalization (coating/material/grade) and re-renders JSON.
    """

    def __init__(self, normalizer=None) -> None:
        # normalizer: callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
        self.normalizer = normalizer

    def _parse_mapping(self, text: str) -> Dict[str, Dict[str, str]]:
        """Extract token -> attribute hints from instructions like 'treat ZP as coating=zinc plated'."""
        mapping: Dict[str, Dict[str, str]] = {}
        lowered = text.lower()
        # treat X as Y
        for m in re.finditer(r"treat\s+([\w\.]+)\s+as\s+([^,\n;]+)", lowered):
            token = m.group(1).strip()
            target = m.group(2).strip()
            entry: Dict[str, str] = {}
            if "coat" in target or "zinc" in target:
                entry["coating"] = target.replace("coating", "").replace("=", "").strip() or "zinc plated"
            if "material" in target or "stainless" in target:
                entry["material"] = target.replace("material", "").replace("=", "").strip()
            if re.match(r"^\d+\.\d+$", target):
                entry["grade"] = target
            if not entry:
                entry["material"] = target
            mapping[token] = entry

        # X = Y style
        for m in re.finditer(r"([\w\.]+)\s*=\s*([^,\n;]+)", lowered):
            token = m.group(1).strip()
            target = m.group(2).strip()
            entry: Dict[str, str] = {}
            if "coat" in target or "zinc" in target:
                entry["coating"] = target.replace("coating", "").replace("=", "").strip() or "zinc plated"
            if "material" in target or "stainless" in target:
                entry["material"] = target.replace("material", "").replace("=", "").strip()
            if re.match(r"^\d+\.\d+$", target):
                entry["grade"] = target
            if not entry:
                entry["material"] = target
            mapping[token] = entry
        return mapping

    def _apply_token_map(self, rows: List[Dict[str, Any]], token_map: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
        updated = copy.deepcopy(rows)
        for row in updated:
            for token, attrs in token_map.items():
                for key, val in list(row.items()):
                    if not isinstance(val, str):
                        continue
                    val_lower = val.lower()
                    if token in val_lower.split() or val_lower == token:
                        # Move misclassified tokens
                        if "coating" in attrs:
                            row["coating"] = attrs["coating"]
                            if key != "coating" and row.get(key) == val:
                                row[key] = None
                        if "material" in attrs:
                            row["material"] = attrs["material"]
                            if key != "material" and row.get(key) == val:
                                row[key] = None
                        if "grade" in attrs:
                            row["grade"] = attrs["grade"]
                            if key != "grade" and row.get(key) == val:
                                row[key] = None
            # If coating accidentally in material, fix
            if isinstance(row.get("material"), str) and row["material"].lower() in token_map:
                maybe = token_map[row["material"].lower()]
                if "coating" in maybe:
                    row["coating"] = maybe["coating"]
                    row["material"] = None
        return updated

    def apply_patch(self, user_message: str, artifact: Any) -> PatchResult:
        if not isinstance(artifact, list) or (artifact and not isinstance(artifact[0], dict)):
            return PatchResult(updated_artifact=None, rendered="Unable to patch: artifact not tabular.", notes=["unsupported_artifact"])

        token_map = dict(DEFAULT_TOKEN_MAP)
        parsed = self._parse_mapping(user_message)
        token_map.update(parsed)

        updated_rows = self._apply_token_map(artifact, token_map)
        if self.normalizer:
            updated_rows = self.normalizer(updated_rows)

        rendered = "Updated output:\n```json\n" + json.dumps(updated_rows, indent=2) + "\n```"
        notes = ["patched_with_token_map"] + (["custom_mappings"] if parsed else [])
        return PatchResult(updated_artifact=updated_rows, rendered=rendered, notes=notes)
