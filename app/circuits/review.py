from __future__ import annotations

from typing import Dict

from app.models import ContentPackage, JudgeDecision, Message, MethodPlan, ReviewReport


class ReviewJudgeCircuit:
    def run(
        self, run_id: str, method_plan: MethodPlan, content_package: ContentPackage
    ) -> Dict[str, ReviewReport | JudgeDecision | Message]:
        content_body = content_package.content.get("raw", "")
        format_ok = all(section.lower() in content_body.lower() for section in method_plan.sections)
        internal_consistency = "high" if format_ok else "medium"
        potential_hallucinations = [] if format_ok else ["Missing sections"]
        notes = []

        review = ReviewReport(
            format_ok=format_ok,
            internal_consistency=internal_consistency,
            potential_hallucinations=potential_hallucinations,
            notes=notes,
        )

        decision_value = "accept" if review.format_ok else "revise"
        decision = JudgeDecision(decision=decision_value, reason="Format check" if not format_ok else "Content consistent")

        message = Message(
            run_id=run_id,
            sender="PuhemiesAgentti",
            recipient="TarkastusPiiri",
            role="result",
            payload={"review": review.__dict__, "decision": decision.__dict__},
        )

        return {"review": review, "decision": decision, "message": message}
