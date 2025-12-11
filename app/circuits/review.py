from __future__ import annotations

from typing import Dict

from app.models import ContentPackage, JudgeDecision, Message, MethodPlan, ReviewReport


class ReviewJudgeCircuit:
    def run(
        self, run_id: str, method_plan: MethodPlan, content_package: ContentPackage
    ) -> Dict[str, ReviewReport | JudgeDecision | Message]:
        missing_sections = [
            s
            for s in method_plan.sections
            if s not in content_package.content or not content_package.content[s].strip()
        ]
        total_sections = len(method_plan.sections) or 1
        section_coverage = 1 - (len(missing_sections) / total_sections)

        format_ok = content_package.method_respected and len(missing_sections) == 0
        internal_consistency = "high" if format_ok else "medium"
        potential_hallucinations = [] if format_ok else [f"Missing sections: {', '.join(missing_sections)}"]
        notes = content_package.warnings
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
            missing_sections=missing_sections,
            section_coverage=section_coverage,
        )

        decision_value = "accept" if review.format_ok else "revise"
        reason = "Content consistent" if format_ok else "Format or method deviations"
        decision = JudgeDecision(decision=decision_value, reason=reason)
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
