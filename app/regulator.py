from __future__ import annotations

from typing import Dict, List

from app.breathing import apply_deltas
from app.models import BreathingParams, CorrectionPlan, Verdict


class CompassionateRegulator:
    def __init__(self, agent_params: Dict[str, BreathingParams]) -> None:
        self.agent_params = agent_params

    def regulate(
        self,
        verdict: Verdict,
        required_grounding: bool,
        contract: dict | None = None,
    ) -> CorrectionPlan | None:
        # pick underperformer
        ranked = verdict.ranked or list(verdict.scores.keys())
        if not ranked or len(ranked) < 2:
            return None

        # assume winner set; choose lowest truth/task_fit
        lowest = None
        lowest_score = 999
        for aid, sc in verdict.scores.items():
            score_val = (5 - sc.task_fit) + (5 - sc.truth) + (3 - min(3, sc.clarity))
            if score_val > lowest_score:
                continue
            lowest = aid
            lowest_score = score_val

        if not lowest:
            return None

        issues = verdict.issues.get(lowest, []) or self._derive_issues(verdict, lowest, required_grounding)
        intervention, deltas, constraints = self._map_intervention(issues, required_grounding)

        params = self.agent_params.get(lowest, BreathingParams()).clamp()
        self.agent_params[lowest] = apply_deltas(params, deltas)

        return CorrectionPlan(
            agent_id=lowest,
            intervention=intervention,
            parameter_deltas=deltas,
            behavioral_constraints=constraints,
            retry=True,
        )

    def _derive_issues(self, verdict: Verdict, agent_id: str, required_grounding: bool) -> List[str]:
        issues: List[str] = []
        scores = verdict.scores.get(agent_id)
        if not scores:
            return issues
        if required_grounding and scores.truth == 0:
            issues.append("invented facts")
        if scores.task_fit <= 2:
            issues.append("task avoidance")
        if scores.clarity <= 2:
            issues.append("too vague")
        if scores.tone <= 1:
            issues.append("tone too harsh")
        return issues

    def _map_intervention(
        self, issues: List[str], required_grounding: bool
    ) -> tuple[str, Dict[str, float], List[str]]:
        if required_grounding and any("invented" in i for i in issues):
            return (
                "grounding_breath",
                {"grounding": 0.3, "verbosity": 0.1, "pace": 0.1},
                ["Do not invent facts.", "State if you cannot fetch live data.", "Offer concrete steps to check."],
            )
        if any(i in issues for i in ["task avoidance", "too vague"]):
            return (
                "breath_up",
                {"initiative": 0.3, "verbosity": 0.1},
                ["Answer the question directly.", "Give at least 2 concrete suggestions.", "No refusal or evasion.", "Stay on topic; no jokes unless explicitly asked."],
            )
        if any("harsh" in i or "tone" in i for i in issues):
            return (
                "breath_down",
                {"softness": 0.25, "pace": 0.15, "initiative": -0.05},
                ["Acknowledge the user before advising.", "Keep tone gentle."],
            )
        # default mild nudge
        return (
            "breath_up",
            {"initiative": 0.1},
            ["Provide one useful step."],
        )
