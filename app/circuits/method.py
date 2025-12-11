from __future__ import annotations

import re
from typing import Dict, List

from app.models import ContentPackage, Message, MethodPlan, ReviewReport, TaskSpec
from app.utils.llm_client import LLMClient


class MethodProducerCircuit:
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

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", "_", text.lower().strip())

    def _extract_sections(self, raw: str, sections: List[str]) -> Dict[str, str]:
        content_map = {section: "" for section in sections}
        normalized_required = {self._normalize(name): name for name in sections}
        current: str | None = None
        buffer: List[str] = []

        for line in raw.splitlines():
            heading_match = re.match(r"^\s*#{1,2}\s*(.+)$", line)
            if heading_match:
                heading_text = heading_match.group(1).strip()
                heading_core = re.split(r"[:\-–—]|[.!?]", heading_text, 1)[0].strip()
                heading_core = heading_core.rstrip(" .,:;–—-")
                normalized_heading = self._normalize(heading_core)
                key = normalized_required.get(normalized_heading)
                if current:
                    content_map[current] = "\n".join(buffer).strip()
                if key:
                    current = key
                else:
                    current = None
                buffer = []
                continue

            if current:
                buffer.append(line)

        if current:
            content_map[current] = "\n".join(buffer).strip()

        return {k: v for k, v in content_map.items() if v.strip()}

    def _build_prompt(self, task_spec: TaskSpec, method_key: str) -> str:
        method_def = self.METHOD_DEFINITIONS[method_key]
        sections: List[str] = method_def["sections"]  # type: ignore[index]
        section_schemas: Dict[str, str] = method_def["section_schemas"]  # type: ignore[index]
        section_help = "\n".join(
            [f"- {section}: {section_schemas.get(section, '')}" for section in sections]
        )
        heading_help = (
            "Label each section with a Markdown heading using '# <section>' or '## <section>'. "
            "You may include punctuation or short clarifiers after the name (e.g., '# Title: ...' or "
            "'## Concept – overview'), but the section name must be the first token in the heading."
        )

        constraints = ", ".join(task_spec.constraints)
        if constraints:
            constraints_line = f"Constraints: {constraints}\n"
        else:
            constraints_line = ""

        return (
            "You are MetodiAgentti followed by TuottajaAgentti. Use the provided method to build content.\n"
            f"Task type: {task_spec.task_type} ({method_def['description']}).\n"
            f"Method: {method_def['format']} with sections {sections}.\n"
            f"Section schema:\n{section_help}\n"
            f"Intent: topic={task_spec.topic}, language={task_spec.language}, target_level={task_spec.target_level}.\n"
            f"{constraints_line}"
            f"{heading_help}\n"
            "Return the content labeled per section in Markdown."
        )

    def run(
        self,
        run_id: str,
        task_spec: TaskSpec,
        prior_review: ReviewReport | None = None,
        revision_number: int = 0,
        method_key: str | None = None,
    ) -> Dict[str, MethodPlan | ContentPackage | Message | Dict[str, str]]:
        resolved_method_key = method_key or self.resolve_method_key(task_spec.task_type)
        method_def = self.METHOD_DEFINITIONS[resolved_method_key]
        sections: List[str] = method_def["sections"]  # type: ignore[index]
        method_plan = MethodPlan(format=method_def["format"], sections=sections)  # type: ignore[index]
        prompt = self._build_prompt(task_spec, resolved_method_key)
        if prior_review:
            prompt += (
                f"This is revision #{revision_number}. Address prior review feedback and fill all missing sections.\n"
                f"Prior review missing sections: {prior_review.missing_sections}. Notes: {prior_review.notes}.\n"
            )

        generated = self.llm.generate(prompt)

        sections_content = self._extract_sections(generated, method_plan.sections)
        missing_sections = [s for s in method_plan.sections if s not in sections_content]

        method_respected = len(missing_sections) == 0
        warnings: List[str] = []
        if missing_sections:
            warnings.append(f"Missing sections: {', '.join(missing_sections)}")

        content = {"format": method_plan.format, **sections_content, "raw": generated}

        package = ContentPackage(
            run_id=run_id,
            content=content,
            method_respected=method_respected,
            warnings=warnings,
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

        return {
            "method_plan": method_plan,
            "content_package": package,
            "message": message,
            "sections_content": sections_content,
        }
