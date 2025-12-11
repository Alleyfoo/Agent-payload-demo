from __future__ import annotations

from typing import Dict, List

from app.models import ContentPackage, Message, MethodPlan, ReviewReport, TaskSpec
from app.utils.llm_client import LLMClient


class MethodProducerCircuit:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def _normalize(self, text: str) -> str:
        return text.lower().strip().replace(" ", "_")

    def _select_method(self, task_spec: TaskSpec) -> MethodPlan:
        method_library = {
            "lesson_page": MethodPlan(
                format="lesson_v1",
                sections=["title", "concept", "code_example", "exercise"],
            ),
            "qa": MethodPlan(
                format="qa_v1",
                sections=["question", "answer", "follow_up"],
            ),
            "cheatsheet": MethodPlan(
                format="cheatsheet_v1",
                sections=["summary", "snippets", "pitfalls", "shortcuts"],
            ),
        }
        return method_library.get(task_spec.task_type, method_library["lesson_page"])

    def _extract_sections(self, text: str, required: List[str]) -> Dict[str, str]:
        sections: Dict[str, str] = {name: "" for name in required}
        current_key: str | None = None
        normalized_required = {self._normalize(name): name for name in required}

        for line in text.splitlines():
            stripped = line.lstrip("# ").strip()
            if line.startswith("#"):
                key = normalized_required.get(self._normalize(stripped))
                if key:
                    current_key = key
                    sections[current_key] = ""
                else:
                    current_key = None
                continue
            if current_key:
                sections[current_key] += ("\n" if sections[current_key] else "") + line
        return {k: v.strip() for k, v in sections.items() if v.strip()}

    def _build_prompt(
        self,
        task_spec: TaskSpec,
        method_plan: MethodPlan,
        revision_number: int,
        prior_review: ReviewReport | None,
    ) -> str:
        base = (
            "You are MetodiAgentti followed by TuottajaAgentti. Use the provided method to build content.\n"
            f"Method: {method_plan.format} with sections {method_plan.sections}.\n"
            f"Intent: topic={task_spec.topic}, language={task_spec.language}, target_level={task_spec.target_level}.\n"
        )
        if revision_number > 0:
            base += f"This is revision #{revision_number}. Address prior review feedback and fill all missing sections.\n"
        if prior_review:
            base += (
                f"Prior review missing sections: {prior_review.missing_sections}."
                f" Notes: {prior_review.notes}.\n"
            )
        return base + "Return the content labeled per section in Markdown."

    def run(
        self,
        run_id: str,
        task_spec: TaskSpec,
        prior_review: ReviewReport | None = None,
        revision_number: int = 0,
    ) -> Dict[str, MethodPlan | ContentPackage | Message]:
        method_plan = self._select_method(task_spec)
        prompt = self._build_prompt(task_spec, method_plan, revision_number, prior_review)
        generated = self.llm.generate(prompt)

        section_bodies = self._extract_sections(generated, method_plan.sections)
        missing_sections = [s for s in method_plan.sections if s not in section_bodies]

        content = {"format": method_plan.format, **section_bodies, "raw": generated}

        method_respected = len(missing_sections) == 0
        warnings = []
        if missing_sections:
            warnings.append(f"Missing sections: {', '.join(missing_sections)}")

        package = ContentPackage(
            run_id=run_id,
            content=content,
            method_respected=method_respected,
            warnings=warnings,
            revision_number=revision_number,
        )

        message = Message(
            run_id=run_id,
            sender="PuhemiesAgentti",
            recipient="MetodiPiiri",
            role="result",
            payload={
                "method": method_plan.format,
                "sections": method_plan.sections,
                "content": generated,
                "revision": revision_number,
            },
        )
        return {"method_plan": method_plan, "content_package": package, "message": message}
