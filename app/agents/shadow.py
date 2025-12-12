from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

from app.models import ContentPackage, JudgeDecision, Message, MethodPlan, ReviewReport


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
        decision: Optional[JudgeDecision],
    ) -> Dict[str, object]:
        coverage_gap = 1 - review.section_coverage
        format_violations = len(review.missing_sections)
        warning_penalty = len(review.notes) * 0.05
        revision_penalty = content_package.revision_number * 0.08
        fact_accuracy_score = self._fact_accuracy_score(review)
        grammar_clarity_score = self._grammar_clarity_score(run_id, content_package)
        revision_depth = len(revision_history)
        section_completion_rate = self._section_completion_rate(
            method_plan.sections, content_package.content
        )
        revision_churn = self._revision_churn(revision_history)
        churn_penalty = min(0.25, revision_churn * 0.04)
        drift_velocity = self._drift_velocity("drift_score")
        coverage_trend = self._drift_velocity("section_completion_rate")
        trace = self._build_trace(run_id)
        graph = self._build_graph(trace)

        drift_dimensions = {
            "format_adherence": round(review.section_coverage, 3),
            "coverage_gap": round(coverage_gap, 3),
            "warning_pressure": round(warning_penalty, 3),
            "revision_pressure": round(revision_penalty, 3),
            "fact_accuracy": round(fact_accuracy_score, 3),
            "grammar_clarity": round(grammar_clarity_score, 3),
            "revision_depth": revision_depth,
            "section_completion": section_completion_rate,
            "revision_churn": revision_churn,
            "drift_velocity": drift_velocity,
            "coverage_trend": coverage_trend,
        }

        drift_score = min(
            1.0,
            round(
                coverage_gap
                + warning_penalty
                + revision_penalty
                + churn_penalty
                + (1 - fact_accuracy_score) * 0.6
                + (1 - grammar_clarity_score) * 0.35
                + max(drift_velocity, 0) * 0.1,
                3,
            ),
        )

        accept_rate = self._acceptance_rate(decision)

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
            "section_completion_rate": section_completion_rate,
            "revision_depth": revision_depth,
            "revision_churn": revision_churn,
            "acceptance_rate": accept_rate,
            "revision_history": revision_history,
            "revision_history_snapshot": revision_history[-3:],
            "review_decision": decision.decision if decision else "unknown",
            "review_reason": decision.reason if decision else "",
            "trace": trace,
            "graph": graph,
            "notes": [m.payload for m in self.messages if m.run_id == run_id],
        }

        aggregates = self._update_aggregates(report)
        report["rolling_aggregates"] = aggregates
        report["historical_trends"] = aggregates.get("historical_trends", {})

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

    def _section_completion_rate(
        self, sections: List[str], content: Dict[str, object]
    ) -> float:
        if not sections:
            return 0.0
        completed = sum(1 for section in sections if str(content.get(section, "")).strip())
        return round(completed / len(sections), 3)

    def _drift_velocity(self, key: str) -> float:
        if len(self.history) < 2:
            return 0.0
        previous = self.history[-1].get(key)
        before_previous = self.history[-2].get(key)
        if not isinstance(previous, (int, float)) or not isinstance(
            before_previous, (int, float)
        ):
            return 0.0
        return round(previous - before_previous, 3)

    def _revision_churn(self, revision_history: List[Dict[str, object]]) -> int:
        churn = 0
        for entry in revision_history:
            added = entry.get("added_sections", [])
            changed = entry.get("changed_sections", [])
            churn += len(added) + len(changed)
        return churn

    def _acceptance_rate(self, decision: Optional[JudgeDecision]) -> float:
        total_runs = len(self.history) + 1
        accepted = sum(
            1 for report in self.history if report.get("review_decision") == "accept"
        )
        if decision and decision.decision == "accept":
            accepted += 1
        return round(accepted / total_runs, 3) if total_runs else 0.0

    def _historical_trends(
        self, reports: List[Dict[str, object]], keys: List[str], window: int = 5
    ) -> Dict[str, Dict[str, object]]:
        trends: Dict[str, Dict[str, object]] = {}
        window_reports = reports[-window:]
        for key in keys:
            values = [
                report.get(key)
                for report in window_reports
                if isinstance(report.get(key), (int, float))
            ]
            if len(values) < 2:
                continue
            trends[key] = {
                "delta": round(values[-1] - values[0], 3),
                "min": min(values),
                "max": max(values),
                "spark": values,
            }
        return trends

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
            "section_completion_rate": moving_average("section_completion_rate", window),
            "revision_depth": moving_average("revision_depth", window),
            "acceptance_rate": moving_average("acceptance_rate", window),
        }
        historical_trends = self._historical_trends(
            combined_history,
            [
                "drift_score",
                "fact_accuracy_score",
                "grammar_clarity_score",
                "format_violations",
                "section_coverage",
                "section_completion_rate",
                "revision_depth",
                "acceptance_rate",
            ],
        )

        aggregates = {
            "total_runs": len(combined_history),
            "decision_counts": decision_counts,
            "rolling_averages": rolling_averages,
            "historical_trends": historical_trends,
        }

        self.history = combined_history
        return aggregates

    def _build_trace(self, run_id: str) -> List[Dict[str, object]]:
        trace: List[Dict[str, object]] = []
        for message in self.messages:
            if message.run_id != run_id:
                continue
            trace.append(
                {
                    "sender": message.sender,
                    "recipient": message.recipient,
                    "role": message.role,
                    "timestamp": message.timestamp,
                    "payload": message.payload,
                }
            )
        return trace

    def _build_graph(self, trace: List[Dict[str, object]]) -> Dict[str, object]:
        nodes: Dict[str, Dict[str, str]] = {}
        edge_map: Dict[tuple[str, str], Dict[str, object]] = {}

        for entry in trace:
            sender = str(entry.get("sender", "unknown"))
            recipient = str(entry.get("recipient", "unknown"))
            nodes[sender] = {"id": sender}
            nodes[recipient] = {"id": recipient}

            key = (sender, recipient)
            if key not in edge_map:
                edge_map[key] = {
                    "source": sender,
                    "target": recipient,
                    "count": 0,
                    "roles": [],
                    "latest_timestamp": entry.get("timestamp"),
                }

            edge = edge_map[key]
            edge["count"] = int(edge["count"]) + 1  # type: ignore[assignment]
            role = entry.get("role")
            if isinstance(role, str) and role not in edge["roles"]:  # type: ignore[index]
                edge["roles"].append(role)  # type: ignore[index]
            edge["latest_timestamp"] = entry.get("timestamp")

        return {
            "nodes": list(nodes.values()),
            "edges": list(edge_map.values()),
        }

    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, object]]:
        if limit is None or limit <= 0:
            return list(self.history)
        return self.history[-limit:]

    def get_run(self, run_id: str) -> Optional[Dict[str, object]]:
        for report in reversed(self.history):
            if report.get("run_id") == run_id:
                return report
        return None
