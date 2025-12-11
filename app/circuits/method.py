from __future__ import annotations

from typing import Dict, List

from app.models import ContentPackage, Message, MethodPlan, TaskSpec
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
    METHOD_DEFINITIONS: Dict[str, Dict[str, object]] = {
        "lesson_page": {
            "format": "lesson_v1",
            "description": "Short lesson page with theory and practice",
            "sections": ["title", "concept", "code_example", "exercise"],
            "section_schemas": {
                "title": "One-line heading for the lesson.",
                "concept": "Concise explanation of the main idea in plain language.",
                "code_example": "Minimal code snippet that illustrates the idea with comments.",
                "exercise": "Single practice task with clear instructions and expected outcome.",
            },
        },
        "tutorial": {
            "format": "tutorial_v1",
            "description": "Step-by-step walkthrough to accomplish a practical goal",
            "sections": ["title", "overview", "steps", "validation", "next_steps"],
            "section_schemas": {
                "title": "Name of the tutorial with the final outcome.",
                "overview": "What the learner will achieve, prerequisites, and estimated effort.",
                "steps": "Numbered list of concrete actions with commands or code per step.",
                "validation": "How to verify the tutorial worked (expected output, tests, or checkpoints).",
                "next_steps": "Where to continue learning or variations to try.",
            },
        },
        "reference": {
            "format": "reference_v1",
            "description": "Concise reference sheet for quickly recalling syntax and options",
            "sections": ["summary", "api_surface", "usage_examples", "caveats"],
            "section_schemas": {
                "summary": "One-paragraph description of the feature or tool.",
                "api_surface": "Bullet list of key commands, functions, or arguments with short notes.",
                "usage_examples": "Multiple short examples covering common cases.",
                "caveats": "Edge cases, limitations, and warnings to remember.",
            },
        },
        "troubleshooting": {
            "format": "troubleshoot_v1",
            "description": "Diagnostics and fixes for a specific error or failure mode",
            "sections": ["issue_summary", "root_causes", "diagnostic_steps", "fixes", "prevention"],
            "section_schemas": {
                "issue_summary": "Plain-language description of the symptom or error message.",
                "root_causes": "Likely causes prioritized from most to least common.",
                "diagnostic_steps": "Ordered checks or commands to narrow down the cause.",
                "fixes": "Concrete remediation steps matched to each cause.",
                "prevention": "Habits or configuration tips to avoid recurrence.",
            },
        },
    }

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def resolve_method_key(self, task_type: str) -> str:
        if task_type in self.METHOD_DEFINITIONS:
            return task_type
        return "lesson_page"

    def _build_prompt(self, task_spec: TaskSpec, method_key: str) -> str:
        method_def = self.METHOD_DEFINITIONS[method_key]
        sections: List[str] = method_def["sections"]  # type: ignore[index]
        section_schemas: Dict[str, str] = method_def["section_schemas"]  # type: ignore[index]
        section_help = "\n".join(
            [f"- {section}: {section_schemas.get(section, '')}" for section in sections]
        )

        return (
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
            f"Task type: {task_spec.task_type} ({method_def['description']}).\n"
            f"Method: {method_def['format']} with sections {sections}.\n"
            f"Section schema:\n{section_help}\n"
            f"Intent: topic={task_spec.topic}, language={task_spec.language}, target_level={task_spec.target_level}.\n"
            "Constraints: " + ", ".join(task_spec.constraints) + "\n"
            "Return the content labeled per section in Markdown."
        )

    def run(
        self, run_id: str, task_spec: TaskSpec, method_key: str | None = None
    ) -> Dict[str, MethodPlan | ContentPackage | Message]:
        resolved_method_key = method_key or self.resolve_method_key(task_spec.task_type)
        method_def = self.METHOD_DEFINITIONS[resolved_method_key]
        sections: List[str] = method_def["sections"]  # type: ignore[index]
        method_plan = MethodPlan(format=method_def["format"], sections=sections)  # type: ignore[index]
        prompt = self._build_prompt(task_spec, resolved_method_key)
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
            method_respected=method_respected,
            warnings=warnings,
            revision_number=revision_number,
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
                "revision": revision_number,
            },
        )
        return {"method_plan": method_plan, "content_package": package, "message": message}
                "task_type": task_spec.task_type,
                "method": method_plan.format,
                "sections": method_plan.sections,
                "content": generated,
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
