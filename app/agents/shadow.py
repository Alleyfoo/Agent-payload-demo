from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from statistics import mean

from app.models import ContentPackage, Message, MethodPlan, ReviewReport


class ShadowAgent:
    def __init__(self, storage_path: Path = Path("data/shadow_reports.jsonl")) -> None:
        self.storage_path = storage_path
        self.messages: List[Message] = []

    def observe(self, message: Message) -> None:
        self.messages.append(message)

    def summarize(
        self,
        run_id: str,
        review: ReviewReport,
        method_plan: MethodPlan,
        content_package: ContentPackage,
    ) -> Dict[str, object]:
        format_violations = len(review.missing_sections)
        warning_penalty = len(review.notes) * 0.05
        revision_penalty = content_package.revision_number * 0.05
        drift_score = max(
            0.0, (1 - review.section_coverage) + warning_penalty + revision_penalty
        )

        history = self._load_reports()
        history_drift = [r.get("drift_score", 0.0) for r in history]
        avg_drift = mean(history_drift) if history_drift else 0.0

        report = {
            "run_id": run_id,
            "pipeline": ["IntentioPiiri", "MetodiPiiri", "TarkastusPiiri"],
            "drift_score": round(drift_score, 3),
            "format_violations": format_violations,
            "hallucination_risk": "low" if review.format_ok else "medium",
            "uncertainty_expressed": not review.format_ok,
            "section_coverage": round(review.section_coverage, 2),
            "warnings": len(review.notes),
            "method": method_plan.format,
            "revision": content_package.revision_number,
            "history": {
                "total_runs": len(history) + 1,
                "avg_drift": round((avg_drift * len(history) + drift_score) / (len(history) + 1), 3),
                "recent_format_violations": sum(
                    r.get("format_violations", 0) for r in history[-4:]
                )
                + format_violations,
            },
            "notes": [m.payload for m in self.messages if m.run_id == run_id],
        }
        self._persist(report)
        self._prune(run_id)
        return report

    def _persist(self, report: Dict[str, object]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")

    def _load_reports(self) -> List[Dict[str, object]]:
        if not self.storage_path.exists():
            return []
        with self.storage_path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _prune(self, run_id: str) -> None:
        # keep only messages that don't belong to completed run to avoid unbounded growth
        self.messages = [m for m in self.messages if m.run_id != run_id]
