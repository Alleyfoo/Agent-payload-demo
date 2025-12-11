from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

from app.models import Message, ReviewReport


class ShadowAgent:
    def __init__(self, storage_path: Path = Path("data/shadow_reports.jsonl")) -> None:
        self.storage_path = storage_path
        self.messages: List[Message] = []
        self.history = self._load_history()

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
        self, run_id: str, review: ReviewReport, revision_history: List[Dict[str, object]]
    ) -> Dict[str, object]:
        format_violations = 0 if review.format_ok else 1
        fact_accuracy_score = self._fact_accuracy_score(review)
        grammar_clarity_score = self._grammar_clarity_score(run_id)
        drift_dimensions = {
            "format_adherence": 1 - format_violations,
            "fact_accuracy": fact_accuracy_score,
            "grammar_clarity": grammar_clarity_score,
        }
        drift_score = mean([1 - drift_dimensions["fact_accuracy"], 1 - drift_dimensions["grammar_clarity"], format_violations * 0.12])
        decision = self._extract_decision(run_id)
        report = {
            "run_id": run_id,
            "pipeline": ["IntentioPiiri", "MetodiPiiri", "TarkastusPiiri"],
            "drift_score": drift_score,
            "format_violations": format_violations,
            "fact_accuracy_score": fact_accuracy_score,
            "grammar_clarity_score": grammar_clarity_score,
            "hallucination_risk": "low" if review.format_ok else "medium",
            "uncertainty_expressed": not review.format_ok,
            "drift_dimensions": drift_dimensions,
            "decision": decision,
            "notes": [m.payload for m in self.messages if m.run_id == run_id],
            "revision_history": revision_history,
        }
        aggregates = self._update_aggregates(report)
        report["rolling_aggregates"] = aggregates
        self._persist(report)
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
    def _load_history(self) -> List[Dict[str, object]]:
        if not self.storage_path.exists():
            return []
        history: List[Dict[str, object]] = []
        with self.storage_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return history

    def _fact_accuracy_score(self, review: ReviewReport) -> float:
        base_score = 1.0
        penalty = 0.15 * len(review.potential_hallucinations)
        return max(0.4, base_score - penalty)

    def _grammar_clarity_score(self, run_id: str) -> float:
        content = self._extract_content(run_id)
        if not content:
            return 0.6
        sentences = [s.strip() for s in content.replace("\n", " ").split(".") if s.strip()]
        avg_sentence_length = mean(len(s.split()) for s in sentences) if sentences else 0
        punctuation_bonus = 0.05 if any(token in content for token in ["?", "!", ";"]) else 0
        clarity = 0.95 if 8 <= avg_sentence_length <= 24 else 0.75
        return min(1.0, clarity + punctuation_bonus)

    def _extract_content(self, run_id: str) -> Optional[str]:
        for message in reversed(self.messages):
            if message.run_id == run_id and "content" in message.payload:
                payload_content = message.payload.get("content")
                if isinstance(payload_content, str):
                    return payload_content
        return None

    def _extract_decision(self, run_id: str) -> str:
        for message in reversed(self.messages):
            if message.run_id != run_id:
                continue
            decision_payload = message.payload.get("decision") if isinstance(message.payload, dict) else None
            if isinstance(decision_payload, dict):
                decision_value = decision_payload.get("decision")
                if isinstance(decision_value, str):
                    return decision_value
        return "unknown"

    def _update_aggregates(self, current_report: Dict[str, object]) -> Dict[str, object]:
        combined_history = self.history + [current_report]
        decisions = [report.get("decision", "unknown") for report in combined_history]
        total_runs = len(combined_history)
        decision_counts = {}
        for dec in decisions:
            decision_counts[dec] = decision_counts.get(dec, 0) + 1

        def moving_average(key: str) -> float:
            values = [report.get(key) for report in combined_history if isinstance(report.get(key), (int, float))]
            return mean(values) if values else 0.0

        aggregates = {
            "total_runs": total_runs,
            "decision_counts": decision_counts,
            "moving_averages": {
                "drift_score": moving_average("drift_score"),
                "fact_accuracy_score": moving_average("fact_accuracy_score"),
                "grammar_clarity_score": moving_average("grammar_clarity_score"),
                "format_violations": moving_average("format_violations"),
            },
        }
        self.history = combined_history
        return aggregates
