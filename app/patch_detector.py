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
        "set",
    ]

    def detect(self, text: str) -> Dict[str, object]:
        lowered = text.lower()
        is_patch = any(verb in lowered for verb in self.PATCH_VERBS)
        treat_pattern = bool(re.search(r"treat\s+.+\s+as\s+.+", lowered))
        update_pattern = bool(re.search(r"re-?output|re-?render", lowered))
        is_patch = is_patch or treat_pattern or update_pattern
        if is_patch:
            return PatchInfo(
                is_patch=True, needs_artifact=True, reason="patch_like_language"
            ).as_dict()
        return PatchInfo().as_dict()
