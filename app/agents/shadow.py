from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

from app.models import (
    CandidateScores,
    ContentPackage,
    JudgeDecision,
    Message,
    MethodPlan,
    ReviewReport,
    Verdict,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE = ROOT_DIR / "data" / "shadow_reports.jsonl"


class ShadowAgent:
    def __init__(self, storage_path: Path = DEFAULT_STORAGE) -> None:
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
        force_guidance: Dict[str, object] | None = None,
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
            "force_guidance": force_guidance,
        }

        aggregates = self._update_aggregates(report)
        report["rolling_aggregates"] = aggregates
        report["historical_trends"] = aggregates.get("historical_trends", {})

        self._persist(report)
        self._prune(run_id)
        return report

    def compare_outputs(
        self,
        run_id: str,
        outputs: List[Dict[str, object]],
        required_grounding: bool = False,
        contract: Dict[str, object] | None = None,
        prune: bool = True,
    ) -> Dict[str, object]:
        """Compare alternative agent outputs and return a verdict. Also capture trace/graph for monitoring."""
        scored: List[Dict[str, object]] = []
        for entry in outputs:
            text = str(entry.get("text", ""))
            label = str(entry.get("label", "unknown"))
            role = str(entry.get("role", "unknown"))
            score_breakdown = self._score_output(entry, contract)
            scored.append(
                {
                    "label": label,
                    "role": role,
                    **score_breakdown,
                    "text": text,
                }
            )

        passing = [s for s in scored if not s.get("gate_violations")]
        if passing:
            pool = passing
            compliant = True
        else:
            pool = scored
            compliant = False
        scored_sorted = sorted(
            pool,
            key=lambda s: (
                len(s.get("gate_violations", [])),
                -(s.get("correctness", 0) or 0),
                -(s.get("truth", 0) or 0),
                -(s.get("task_fit", 0) or 0),
            ),
        )
        if scored_sorted:
            winner = scored_sorted[0]["label"]
            verdict_str = f"{winner} preferred" if compliant else f"{winner} least_bad (noncompliant)"
        else:
            winner = "none"
            verdict_str = "no winner"

        trace = self._build_trace(run_id)
        graph = self._build_graph(trace)

        report = {
            "run_id": run_id,
            "kind": "comparison",
            "pipeline": ["TaoistIntent", "BuddhistHealing", "SelfishControl"],
            "verdict": verdict_str,
            "winner": winner,
            "ranked": [s["label"] for s in scored_sorted],
            "scores": {s["label"]: {k: s[k] for k in ("correctness", "truth", "task_fit", "clarity", "tone", "safety", "utility")} for s in scored_sorted},
            "issues": self._collect_issues(scored_sorted, required_grounding),
            "required_grounding": required_grounding,
            "confidence": 0.8,
            "gate_violations": {s["label"]: s.get("gate_violations", []) for s in scored if s.get("gate_violations")},
            "trace": trace,
            "graph": graph,
            "notes": [m.payload for m in self.messages if m.run_id == run_id],
        }
        report["alternatives"] = scored_sorted

        self.history.append(report)
        self._persist(report)
        if prune:
            self._prune(run_id)
        return report

    def prune_run(self, run_id: str) -> None:
        self._prune(run_id)

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

    def _score_output(self, entry: Dict[str, object], contract: Dict[str, object] | None = None) -> Dict[str, object]:
        """Rubric-based score for healing vs selfish."""
        text = str(entry.get("text", ""))
        header = entry.get("header", {}) if isinstance(entry.get("header", {}), dict) else {}
        required_grounding = bool(header.get("required_grounding", False))
        role = str(entry.get("role", "")).lower()

        truth = 4
        if required_grounding:
            if self._looks_invented_weather(text):
                truth = 0
            elif self._admits_limitation(text):
                truth = 4
            else:
                truth = 2

        lower = text.lower()
        off_topic = "joke" in lower or "vitsi" in lower

        task_fit = 5 if text else 1
        if off_topic and not header.get("task_type") == "joke":
            task_fit = min(task_fit, 1)

        clarity = min(4, text.count("\n") + 1) if text else 1
        if task_fit == 1:
            clarity = min(clarity, 2)

        tone = 3 if "please" in lower or "autan" in lower else 1
        if "jääkaapin" in lower or "ei kannata" in lower:
            tone = min(tone, 2)

        safety = "pass"
        utility = max(1, task_fit)
        correctness = 5 if task_fit >= 3 else 2
        gate_violations: List[str] = []
        if contract:
            hard_gates = contract.get("hard_gates", [])
            deliverables = contract.get("deliverables", [])
            expected_result = contract.get("expected_result")
            patch_requires_artifact = bool(contract.get("patch_requires_artifact"))
            patch_requires_render = bool(contract.get("patch_requires_render"))
            pipeline_required = bool(contract.get("pipeline_required"))
            crypto_sanity_required = bool(contract.get("crypto_sanity_required"))
            math_list_required = bool(contract.get("math_list_required"))
            extraction_required = bool(contract.get("extraction_required"))
            force_guidance_required = bool(contract.get("force_guidance_required"))
            expected_mean = contract.get("math_expected_mean")
            expected_median = contract.get("math_expected_median")
            tip_domain_required = contract.get("tip_domain_required")
            strict_numeric_truth = bool(contract.get("strict_numeric_truth"))
            expected_schema = contract.get("expected_schema")
            fg_schema = contract.get("force_guidance_schema") or [
                "situation_summary",
                "primary_lever",
                "adjacent_options",
                "profile",
                "reason_codes",
                "state_pattern",
            ]
            parsed_json = None
            if extraction_required:
                parsed_json = self._extract_json(text)
                if parsed_json is not None:
                    text = json.dumps(parsed_json, ensure_ascii=False)
            if force_guidance_required and "must_return_force_guidance_json" in hard_gates:
                parsed_json = self._extract_json(text)
                if parsed_json is not None and isinstance(parsed_json, (dict, list)):
                    text = json.dumps(parsed_json, ensure_ascii=False, separators=(",", ":"))
                if not parsed_json or not isinstance(parsed_json, dict):
                    gate_violations.append("force_guidance_invalid_json")
                    correctness = 0
                else:
                    keys = set(parsed_json.keys())
                    if set(fg_schema) != keys:
                        gate_violations.append("force_guidance_schema_mismatch")
                        correctness = 0
                    else:
                        if not isinstance(parsed_json.get("primary_lever"), dict):
                            gate_violations.append("force_guidance_primary_invalid")
                            correctness = 0
                        else:
                            lever = parsed_json["primary_lever"]
                            for req in ["name", "rationale", "first_step"]:
                                if req not in lever:
                                    gate_violations.append("force_guidance_primary_invalid")
                                    correctness = 0
                                    break
                        adj = parsed_json.get("adjacent_options")
                        if not isinstance(adj, list) or len(adj) != 3:
                            gate_violations.append("force_guidance_adjacent_invalid")
                            correctness = 0
                        else:
                            for item in adj:
                                if not isinstance(item, dict) or "name" not in item or "first_step" not in item:
                                    gate_violations.append("force_guidance_adjacent_invalid")
                                    correctness = 0
                                    break
                        profile = parsed_json.get("profile")
                        if not isinstance(profile, dict) or not all(k in profile for k in ["tension", "uncertainty", "inertia", "polarity", "agency"]):
                            gate_violations.append("force_guidance_profile_invalid")
                            correctness = 0
                        if not isinstance(parsed_json.get("reason_codes"), list):
                            gate_violations.append("force_guidance_reason_codes_invalid")
                            correctness = 0
                        if not isinstance(parsed_json.get("state_pattern"), str):
                            gate_violations.append("force_guidance_state_pattern_invalid")
                            correctness = 0
            # Gate: final numeric result
            if "must_include_final_result" in hard_gates:
                final_num = self._extract_final_number(text)
                if final_num is None:
                    gate_violations.append("missing_numeric_result")
                    correctness = 0
                elif expected_result is not None and final_num != expected_result:
                    gate_violations.append("wrong_numeric_result")
                    correctness = 0
                elif strict_numeric_truth and expected_result is not None and final_num != expected_result:
                    gate_violations.append("wrong_numeric_result")
                    correctness = 0
            # Gate: tips count
            tips_needed = None
            for d in deliverables:
                if isinstance(d, dict) and d.get("type") == "advice" and d.get("count"):
                    tips_needed = d.get("count")
            if tips_needed:
                tips_count = self._count_tips(text)
                if tips_count < tips_needed:
                    gate_violations.append("insufficient_advice_items")
                    correctness = 0
            # Gate: must_not_contradict_own_math
            if "must_not_contradict_own_math" in hard_gates and expected_result is not None:
                if self._detect_contradiction(text, expected_result):
                    gate_violations.append("self_contradiction")
                    correctness = 0
            if patch_requires_artifact:
                if not self._mentions_artifact_request(text):
                    gate_violations.append("missing_patch_target_or_request")
                    correctness = 0
            if patch_requires_render:
                if not self._contains_json(text):
                    gate_violations.append("missing_patch_render")
                    correctness = 0
            if pipeline_required and "must_include_pipeline_elements" in hard_gates:
                pipeline_obj = self._extract_pipeline_json(text)
                if not pipeline_obj:
                    gate_violations.append("missing_structured_output")
                    correctness = 0
                else:
                    if self._missing_pipeline_keys(pipeline_obj):
                        gate_violations.append("missing_pipeline_keys")
                        correctness = 0
                    if not self._contains_pipeline_elements(text, pipeline_obj):
                        gate_violations.append("missing_pipeline_elements")
                        correctness = 0
            if crypto_sanity_required and "must_fix_reversible_hash" in hard_gates:
                if self._mentions_reversible_hash_without_fix(text):
                    gate_violations.append("crypto_hash_not_fixed")
                    correctness = 0
            if math_list_required and "must_handle_math_list" in hard_gates:
                if not self._passes_math_list(text, expected_mean, expected_median):
                    gate_violations.append("math_list_incorrect")
                    correctness = 0
            if extraction_required and "must_return_structured_json" in hard_gates:
                parsed = parsed_json if parsed_json is not None else self._extract_json(text)
                if not parsed:
                    gate_violations.append("missing_structured_output")
                    correctness = 0
                else:
                    if expected_schema and isinstance(parsed, list):
                        schema_ok, schema_issue = self._check_schema(parsed, expected_schema)
                        if not schema_ok:
                            gate_violations.append(schema_issue or "schema_mismatch")
                            correctness = 0
                        else:
                            type_ok, type_issue = self._check_length_types(parsed)
                            if not type_ok:
                                gate_violations.append(type_issue or "length_type_invalid")
                                correctness = 0
                            token_ok, token_issue = self._check_token_mapping(parsed)
                            if not token_ok:
                                gate_violations.append(token_issue or "token_misclassified")
                                correctness = 0
                    elif expected_schema:
                        gate_violations.append("schema_mismatch")
                        correctness = 0
            if tip_domain_required:
                if not self._tips_in_domain(text, tip_domain_required):
                    gate_violations.append("tips_off_domain")
                    correctness = 0

        return {
            "truth": truth,
            "task_fit": task_fit,
            "clarity": clarity,
            "tone": tone,
            "safety": safety,
            "utility": utility,
            "off_topic": off_topic,
            "correctness": correctness,
            "gate_violations": gate_violations,
        }

    def _extract_pipeline_json(self, text: str) -> Optional[Dict[str, object]]:
        """Parse pipeline JSON, optionally wrapped with BEGIN/END markers."""
        cleaned = text.strip()
        if cleaned.startswith("BEGIN_PIPELINE_JSON"):
            inner = cleaned.split("BEGIN_PIPELINE_JSON", 1)[1]
            if "END_PIPELINE_JSON" in inner:
                cleaned = inner.split("END_PIPELINE_JSON", 1)[0].strip()
        try:
            return json.loads(cleaned)
        except Exception:
            pass
        # code fences
        blocks = re.findall(r"```json(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        for blk in blocks:
            try:
                return json.loads(blk.strip())
            except Exception:
                continue
        # brace-delimited object
        obj_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if obj_match:
            try:
                return json.loads(obj_match.group(0))
            except Exception:
                return None
        return None

    def _missing_pipeline_keys(self, pipeline_obj: Dict[str, object]) -> List[str]:
        required_keys = ["pipeline_steps", "data_flow", "failure_recovery", "artifacts", "assumptions"]
        missing = [k for k in required_keys if k not in pipeline_obj]
        return missing

    def _contains_pipeline_elements(self, text: str, pipeline_obj: Optional[Dict[str, object]] = None) -> bool:
        required_elements = [
            "ingestion",
            "file_manifest",
            "classification",
            "extraction_text",
            "extraction_tables",
            "ocr_branch",
            "validation",
            "xlsx_writer",
            "audit_log",
            "checkpointing_resume",
            "error_policy",
        ]
        synonyms = {
            "ingestion": ["ingestion", "input"],
            "file_manifest": ["file_manifest", "manifest"],
            "classification": ["classification", "classify"],
            "extraction_text": ["extraction_text", "text_extraction"],
            "extraction_tables": ["extraction_tables", "table_extraction", "tables"],
            "ocr_branch": ["ocr_branch", "ocr"],
            "validation": ["validation", "validate"],
            "xlsx_writer": ["xlsx_writer", "xlsx", "excel"],
            "audit_log": ["audit_log", "audit", "log"],
            "checkpointing_resume": ["checkpointing_resume", "resume", "checkpoint"],
            "error_policy": ["error_policy", "error", "quarantine"],
        }

        def has_element(name: str, candidates: List[str]) -> bool:
            targets = [t.lower() for t in synonyms.get(name, [name])]
            return any(any(t in c for t in targets) for c in candidates)

        candidates: List[str] = []
        if pipeline_obj and isinstance(pipeline_obj.get("pipeline_steps"), list):
            for item in pipeline_obj["pipeline_steps"]:
                if isinstance(item, str):
                    candidates.append(item.lower())
                elif isinstance(item, dict):
                    for val in item.values():
                        if isinstance(val, str):
                            candidates.append(val.lower())
        if not candidates:
            candidates = [text.lower()]

        missing = [name for name in required_elements if not has_element(name, candidates)]
        return len(missing) == 0

    def _mentions_reversible_hash_without_fix(self, text: str) -> bool:
        lower = text.lower()
        mentions_bad = "hash" in lower and "reversible" in lower
        references_fix = any(token in lower for token in ["token", "tokenization", "encrypt", "encryption", "vault"])
        return mentions_bad and not references_fix

    def _passes_math_list(self, text: str, expected_mean: float | None, expected_median: float | None) -> bool:
        """Light check: ensure reported mean/median match expected when provided."""
        lower = text.lower()
        if expected_mean is None and expected_median is None:
            return True
        def _num_in_text(target: float) -> bool:
            return f"{target}" in text or f"{round(target, 2)}" in text or f"{round(target, 1)}" in text

        mean_ok = True
        median_ok = True
        if expected_mean is not None and ("mean" in lower or "average" in lower):
            mean_ok = _num_in_text(expected_mean)
        if expected_median is not None and "median" in lower:
            median_ok = _num_in_text(expected_median)
        return mean_ok and median_ok

    def _tips_in_domain(self, text: str, domain: str) -> bool:
        if domain != "mental_multiplication":
            return True
        lower = text.lower()
        # require mentions of multiply/multiplication/mental math in tips
        return any(k in lower for k in ["multiply", "multiplication", "mental math", "mentally", "product"])

    def _extract_json(self, text: str):
        cleaned = text.strip()
        if cleaned.startswith("BEGIN_PIPELINE_JSON"):
            inner = cleaned.split("BEGIN_PIPELINE_JSON", 1)[1]
            if "END_PIPELINE_JSON" in inner:
                cleaned = inner.split("END_PIPELINE_JSON", 1)[0].strip()
        for candidate in (cleaned,):
            try:
                return json.loads(candidate)
            except Exception:
                continue
        try:
            blocks = re.findall(r"```json(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
            if not blocks:
                blocks = re.findall(r"\{(?:.|\n)*\}", text) or re.findall(r"\[(?:.|\n)*\]", text)
            for blk in blocks:
                return json.loads(blk.strip())
        except Exception:
            return None
        return None

    def _check_schema(self, data, expected_schema) -> tuple[bool, str | None]:
        if not isinstance(data, list) or not data:
            return False, "schema_mismatch"
        for row in data:
            if not isinstance(row, dict):
                return False, "schema_mismatch"
            keys = set(row.keys())
            if expected_schema:
                if keys != set(expected_schema):
                    return False, "schema_mismatch"
        return True, None

    def _check_length_types(self, data) -> tuple[bool, str | None]:
        for row in data:
            if "length" not in row:
                return False, "missing_length_field"
            val = row.get("length")
            if val is None:
                continue
            if isinstance(val, str):
                if val.strip() == "":
                    return False, "length_type_invalid"
                if val.isdigit():
                    continue
                return False, "length_type_invalid"
            if isinstance(val, (int, float)):
                continue
            return False, "length_type_invalid"
        return True, None

    def _check_token_mapping(self, data) -> tuple[bool, str | None]:
        if not isinstance(data, list):
            return False, "schema_mismatch"
        for row in data:
            if not isinstance(row, dict):
                return False, "schema_mismatch"
            material = str(row.get("material", "") or "").lower()
            coating = str(row.get("coating", "") or "").lower()
            # misclassified coating tokens in material
            if any(tok in material for tok in ["zp", "zn", "zinc"]):
                return False, "coating_misclassified"
            if any(tok in coating for tok in ["a2", "a4", "stainless"]):
                return False, "material_misclassified"
        return True, None

    def _extract_final_number(self, text: str) -> int | None:
        match = re.search(r"(answer|result|=)\s*[:=]?\s*(-?\d+)", text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(2))
            except ValueError:
                return None
        # fallback: last integer in text
        nums = re.findall(r"-?\d+", text)
        if nums:
            try:
                return int(nums[-1])
            except ValueError:
                return None
        return None

    def _count_tips(self, text: str) -> int:
        bullet_lines = re.findall(r"(?m)^\s*[-*•]\s+", text)
        numbered_lines = re.findall(r"(?m)^\s*\d+[\.\)]\s+", text)
        tip_tokens = re.findall(r"(?i)(^|\n)\s*(tip|advice|one way|one idea)", text)
        return len(bullet_lines) + len(numbered_lines) + len(tip_tokens)

    def _detect_contradiction(self, text: str, expected: int) -> bool:
        final_num = self._extract_final_number(text)
        if final_num is not None and final_num != expected:
            return True
        return False

    def _mentions_artifact_request(self, text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in ["paste", "provide", "send the data", "previous output", "earlier output", "artifact", "table", "json"])

    def _contains_json(self, text: str) -> bool:
        return bool(re.search(r"\{|\[", text))

    def _collect_issues(self, scored_sorted: List[Dict[str, object]], required_grounding: bool) -> Dict[str, List[str]]:
        issues: Dict[str, List[str]] = {}
        for s in scored_sorted:
            agent_issues: List[str] = []
            if required_grounding and s.get("truth", 0) == 0:
                agent_issues.append("invented facts")
            if s.get("task_fit", 0) <= 2:
                agent_issues.append("task avoidance")
            if s.get("tone", 0) <= 1:
                agent_issues.append("tone too harsh")
            if s.get("clarity", 0) <= 2:
                agent_issues.append("too vague")
            if s.get("utility", 0) <= 2:
                agent_issues.append("low_utility")
            if s.get("off_topic"):
                agent_issues.append("off_topic")
            if s.get("correctness", 0) == 0:
                agent_issues.append("gate_violation")
            if s.get("gate_violations"):
                agent_issues.extend(list(s.get("gate_violations")))
            if agent_issues:
                issues[s.get("label", "unknown")] = agent_issues
        return issues

    def _looks_invented_weather(self, text: str) -> bool:
        lowered = text.lower()
        mentions_temp = "°c" in lowered or "astetta" in lowered or "celsius" in lowered
        mentions_now = "nyt" in lowered or "currently" in lowered
        admits = self._admits_limitation(text)
        return mentions_temp and mentions_now and not admits

    def _admits_limitation(self, text: str) -> bool:
        lowered = text.lower()
        return any(phrase in lowered for phrase in ["en näe", "en voi hakea", "cannot fetch", "ei pääsyä"])

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
