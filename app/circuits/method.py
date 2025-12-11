from __future__ import annotations

from typing import Dict, List

from app.models import ContentPackage, Message, MethodPlan, TaskSpec
from app.utils.llm_client import LLMClient


class MethodProducerCircuit:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        run_id: str,
        task_spec: TaskSpec,
        revision_index: int = 0,
        previous_sections: Dict[str, str] | None = None,
    ) -> Dict[str, MethodPlan | ContentPackage | Message | Dict[str, object]]:
        previous_sections = previous_sections or {}
        method_plan = MethodPlan(format="lesson_v1", sections=["title", "concept", "code_example", "exercise"])
        prompt = (
            "You are MetodiAgentti followed by TuottajaAgentti. Use the provided method to build content.\n"
            f"Method: {method_plan.format} with sections {method_plan.sections}.\n"
            f"Intent: topic={task_spec.topic}, language={task_spec.language}, target_level={task_spec.target_level}.\n"
            "Return the content labeled per section in Markdown."
        )
        generated = self.llm.generate(prompt)

        sections_content = self._extract_sections(generated, method_plan.sections)
        revision_delta = self._build_revision_delta(
            revision_index, method_plan.sections, sections_content, previous_sections
        )

        content = {
            "format": method_plan.format,
            "title": "Example lesson" if "title" not in generated.lower() else None,
            "raw": generated,
        }

        package = ContentPackage(
            run_id=run_id,
            content=content,
            method_respected=True,
            warnings=[],
            revision_history=[revision_delta],
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
                "revision": revision_index,
                "revision_delta": revision_delta,
            },
        )
        return {
            "method_plan": method_plan,
            "content_package": package,
            "message": message,
            "sections_content": sections_content,
            "revision_delta": revision_delta,
        }

    def _extract_sections(self, raw: str, sections: List[str]) -> Dict[str, str]:
        content_map = {section: "" for section in sections}
        current: str | None = None
        buffer: List[str] = []
        for line in raw.splitlines():
            heading = line.lstrip("# ").strip().lower()
            matched_section = next(
                (section for section in sections if section.replace("_", " ").lower() in heading), None
            )
            if matched_section:
                if current:
                    content_map[current] = "\n".join(buffer).strip()
                current = matched_section
                buffer = []
                continue

            if current:
                buffer.append(line)

        if current:
            content_map[current] = "\n".join(buffer).strip()
        return content_map

    def _build_revision_delta(
        self,
        revision_index: int,
        sections: List[str],
        sections_content: Dict[str, str],
        previous_sections: Dict[str, str],
    ) -> Dict[str, object]:
        added_sections = [
            section
            for section in sections
            if not previous_sections.get(section) and sections_content.get(section)
        ]
        changed_sections = [
            section
            for section in sections
            if previous_sections.get(section) and previous_sections.get(section) != sections_content.get(section)
        ]
        return {
            "revision": revision_index,
            "added_sections": added_sections,
            "changed_sections": changed_sections,
        }
