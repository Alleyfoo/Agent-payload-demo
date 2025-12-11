from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

from app.models import ContentPackage, Message, MethodPlan, ReviewReport


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
        revision_history: List[Dict[str, object]],
    ) -> Dict[str, object]:
        coverage_gap = 1 - review.section_coverage
        format_violations = len(review.missing_sections)
        warning_penalty = len(review.notes) * 0.05
        revision_penalty = content_package.revision_number * 0.08
        fact_accuracy_score = self._fact_accuracy_score(review)
        grammar_clarity_score = self._grammar_clarity_score(run_id, content_package)

        drift_dimensions = {
            "format_adherence": round(review.section_coverage, 3),
            "coverage_gap": round(coverage_gap, 3),
            "warning_pressure": round(warning_penalty, 3),
            "revision_pressure": round(revision_penalty, 3),
            "fact_accuracy": round(fact_accuracy_score, 3),
            "grammar_clarity": round(grammar_clarity_score, 3),
        }

        drift_score = min(
            1.0,
            round(
                coverage_gap
                + warning_penalty
                + revision_penalty
                + (1 - fact_accuracy_score) * 0.6
                + (1 - grammar_clarity_score) * 0.4,
                3,
            ),
        )

        report = {
            "run_id": run_id,
            "pipeline": ["IntentioPiiri", "MetodiPiiri", "TarkastusPiiri"],
            "method": method_plan.format,
            "revision": content_package.revision_number,
            "drift_score": drift_score,
            "format_violations": format_violations,
            "fact_accuracy_score": fact_accuracy_score,
            "grammar_clarity_score": grammar_clarity_score,
            "hallucination_risk": "low" if review.format_ok else "medium",
            "uncertainty_expressed": not review.format_ok,
            "drift_dimensions": drift_dimensions,
            "section_coverage": round(review.section_coverage, 3),
            "revision_history": revision_history,
            "notes": [m.payload for m in self.messages if m.run_id == run_id],
        }

        aggregates = self._update_aggregates(report)
        report["rolling_aggregates"] = aggregates

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

    def _grammar_clarity_score(
        self, run_id: str, content_package: ContentPackage
    ) -> float:
        content = self._extract_content(run_id, content_package)
        if not content:
            return 0.6
        sentences = [s.strip() for s in content.replace("\n", " ").split(".") if s.strip()]
        avg_sentence_length = mean(len(s.split()) for s in sentences) if sentences else 0
        punctuation_bonus = 0.05 if any(token in content for token in ["?", "!", ";"]) else 0
        clarity = 0.95 if 8 <= avg_sentence_length <= 24 else 0.75
        return min(1.0, clarity + punctuation_bonus)

    def _extract_content(
        self, run_id: str, content_package: ContentPackage
    ) -> Optional[str]:
        raw_content = content_package.content.get("raw")
        if isinstance(raw_content, str) and raw_content.strip():
            return raw_content
        for message in reversed(self.messages):
            if message.run_id == run_id and "content" in message.payload:
                payload_content = message.payload.get("content")
                if isinstance(payload_content, str):
                    return payload_content
        return None

    def _update_aggregates(self, current_report: Dict[str, object]) -> Dict[str, object]:
        combined_history = self.history + [current_report]
        window = combined_history[-5:]

        def moving_average(key: str, reports: List[Dict[str, object]]) -> float:
            values = [report.get(key) for report in reports if isinstance(report.get(key), (int, float))]
            return round(mean(values), 3) if values else 0.0

        decision_counts: Dict[str, int] = {}
        for report in combined_history:
            decision = report.get("decision") or report.get("review_decision", "unknown")
            if isinstance(decision, dict):
                decision_value = decision.get("decision", "unknown")
            else:
                decision_value = decision if isinstance(decision, str) else "unknown"
            decision_counts[decision_value] = decision_counts.get(decision_value, 0) + 1

        rolling_averages = {
            "drift_score": moving_average("drift_score", window),
            "fact_accuracy_score": moving_average("fact_accuracy_score", window),
            "grammar_clarity_score": moving_average("grammar_clarity_score", window),
            "format_violations": moving_average("format_violations", window),
            "section_coverage": moving_average("section_coverage", window),
        }

        if len(window) > 1:
            previous = window[-2]
            rolling_trends = {
                key: round(current_report.get(key, 0) - previous.get(key, 0), 3)
                for key in [
                    "drift_score",
                    "fact_accuracy_score",
                    "grammar_clarity_score",
                    "format_violations",
                    "section_coverage",
                ]
                if isinstance(current_report.get(key), (int, float))
                and isinstance(previous.get(key), (int, float))
            }
        else:
            rolling_trends = {}

        aggregates = {
            "total_runs": len(combined_history),
            "decision_counts": decision_counts,
            "rolling_averages": rolling_averages,
            "rolling_trends": rolling_trends,
        }

        self.history = combined_history
        return aggregates
