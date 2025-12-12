from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Dict


@dataclass
class PatchInfo:
    is_patch: bool = False
    needs_artifact: bool = False
    reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "is_patch": self.is_patch,
            "needs_artifact": self.needs_artifact,
            "reason": self.reason,
        }


class PatchDetector:
    PATCH_VERBS = [
        "update",
        "re-output",
        "reoutput",
        "re render",
        "rerender",
        "apply",
        "change",
        "replace",
        "patch",
        "adjust",
        "fix",
        "treat",
    ]
    CONTEXT_ANCHORS = [
        "previous",
        "edellinen",
        "above",
        "list",
        "table",
        "taulukko",
        "artefakti",
        "artifact",
        "json",
        "jsonpath",
        "row",
        "rows",
        "column",
        "col",
        "field",
        "key",
        "entry",
    ]

    def detect(self, text: str) -> Dict[str, object]:
        lowered = text.lower()
        has_anchor = any(anchor in lowered for anchor in self.CONTEXT_ANCHORS)
        structural_ref = bool(re.search(r"(row\s*\d+|column\s*\w+|field\s+\w+|key\s+\w+|\[\d+\]|(?:\$|\.)\w+)", lowered))
        verb_hit = any(re.search(rf"\b{re.escape(verb)}\b", lowered) for verb in self.PATCH_VERBS)
        treat_pattern = bool(re.search(r"treat\s+.+\s+as\s+.+", lowered))
        update_pattern = bool(re.search(r"re-?output|re-?render", lowered))
        set_clause = bool(re.search(r"\bset\s+[\w\.\[\]]+\s+(to|as)\s+", lowered))

        is_patch = (verb_hit or treat_pattern or update_pattern or set_clause) and (has_anchor or structural_ref or set_clause)
        if is_patch:
            if update_pattern:
                reason = "rerender_request"
            elif treat_pattern:
                reason = "treat_pattern"
            elif set_clause:
                reason = "set_clause"
            else:
                reason = "verb_with_anchor"
            return PatchInfo(
                is_patch=True, needs_artifact=True, reason=reason
            ).as_dict()
        return PatchInfo().as_dict()
