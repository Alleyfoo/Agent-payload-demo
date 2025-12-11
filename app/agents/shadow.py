from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from app.models import Message, ReviewReport


class ShadowAgent:
    def __init__(self, storage_path: Path = Path("data/shadow_reports.jsonl")) -> None:
        self.storage_path = storage_path
        self.messages: List[Message] = []

    def observe(self, message: Message) -> None:
        self.messages.append(message)

    def summarize(self, run_id: str, review: ReviewReport) -> Dict[str, object]:
        format_violations = 0 if review.format_ok else 1
        drift_score = format_violations * 0.12
        report = {
            "run_id": run_id,
            "pipeline": ["IntentioPiiri", "MetodiPiiri", "TarkastusPiiri"],
            "drift_score": drift_score,
            "format_violations": format_violations,
            "hallucination_risk": "low" if review.format_ok else "medium",
            "uncertainty_expressed": not review.format_ok,
            "notes": [m.payload for m in self.messages if m.run_id == run_id],
        }
        self._persist(report)
        return report

    def _persist(self, report: Dict[str, object]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
