from __future__ import annotations

import re
from typing import Dict, List

from app.models import ContentPackage, Message, MethodPlan, ReviewReport, TaskSpec
from app.utils.llm_client import LLMClient


class MethodProducerCircuit:
    METHOD_DEFINITIONS: Dict[str, Dict[str, object]] = {
        "project_plan": {
            "format": "project_plan_v1",
            "description": "Milestone-focused delivery plan with risks and owners",
            "sections": ["objective", "deliverables", "milestones", "risks", "owners"],
            "section_schemas": {
                "objective": "One-sentence goal with measurable success criteria.",
                "deliverables": "Bullet list of tangible outputs with due dates.",
                "milestones": "Ordered checkpoints with dates and success signals.",
                "risks": "Top risks with likelihood, impact, and mitigation steps.",
                "owners": "Who is accountable for each milestone/deliverable.",
            },
            "guidance": "Be concrete about dates and mitigation. Keep wording action-oriented.",
        },
        "study_guide": {
            "format": "study_guide_v1",
            "description": "Condensed study guide with checkpoints and self-test",
            "sections": ["title", "prerequisites", "key_concepts", "checkpoints", "self_test"],
            "section_schemas": {
                "title": "Name of the unit or topic.",
                "prerequisites": "What the learner must know first (links or bullet points).",
                "key_concepts": "3-5 core ideas with one-line summaries.",
                "checkpoints": "Milestones the learner should achieve in order.",
                "self_test": "3-4 short questions or prompts to verify understanding.",
            },
            "guidance": "Prioritize brevity and clarity. Keep checkpoints outcome-oriented.",
        },
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
        "qa": {
            "format": "qa_v1",
            "description": "Structured question answering with concise evidence",
            "sections": ["question", "answer", "supporting_points", "follow_up"],
            "section_schemas": {
                "question": "Restate the user's question in your own words.",
                "answer": "Direct, complete answer in 3–6 sentences.",
                "supporting_points": "Bulleted facts, citations, or short code that back up the answer.",
                "follow_up": "Two suggested follow-up questions or next actions for the user.",
            },
            "guidance": "Answer first, then provide evidence. Keep tone helpful and focused on the user's intent.",
            "examples": [
                "# Question: How do I append to a Python list?\n",
                "## Answer: Use list.append(item) to add a single element to the end.\n",
                "## Supporting_points:\n- append mutates the existing list in-place.\n- For multiple items at once, prefer list.extend(iterable).\n",
                "## Follow_up: What if I need to insert at a specific position?; How do I avoid duplicates?",
            ],
        },
        "cheatsheet": {
            "format": "cheatsheet_v1",
            "description": "Rapid-look cheat sheet with snippets and pitfalls",
            "sections": ["summary", "snippets", "pitfalls", "shortcuts"],
            "section_schemas": {
                "summary": "One-paragraph refresher of the topic and why it matters.",
                "snippets": "Compact code or command snippets with one-line explanations.",
                "pitfalls": "Common mistakes and how to avoid or detect them.",
                "shortcuts": "Short tips, flags, or editor tricks that save time.",
            },
            "guidance": "Favor brevity and skimmability. Lead with defaults, then power tips.",
            "examples": [
                "# Summary: Git branching essentials for quick fixes.\n",
                "## Snippets:\n- git checkout -b hotfix/issue-123\n- git cherry-pick <commit>  # bring in one change\n",
                "## Pitfalls:\n- Avoid force-pushing shared branches; use --force-with-lease if needed.\n",
                "## Shortcuts: git switch <branch>; git restore --staged <file> to unstage.",
            ],
        },
        "design_doc": {
            "format": "design_doc_v1",
            "description": "Architecture design document with decisions and rationale",
            "sections": [
                "context",
                "goals",
                "non_goals",
                "architecture",
                "tradeoffs",
                "open_questions",
            ],
            "section_schemas": {
                "context": "Problem statement, stakeholders, and constraints.",
                "goals": "Numbered, testable goals for the design.",
                "non_goals": "Out-of-scope items that will not be addressed.",
                "architecture": "Proposed system shape with components and data flows.",
                "tradeoffs": "Key alternatives considered and why this design was chosen.",
                "open_questions": "Known unknowns, risks, and follow-ups.",
            },
            "guidance": "Prefer diagrams-in-words and be explicit about decisions and risks.",
        },
        "postmortem": {
            "format": "postmortem_v1",
            "description": "Blameless incident review with corrective actions",
            "sections": [
                "incident_summary",
                "impact",
                "root_cause",
                "timeline",
                "corrective_actions",
                "prevention",
            ],
            "section_schemas": {
                "incident_summary": "Short description with when, what, who was affected.",
                "impact": "Customer/user impact, duration, and severity.",
                "root_cause": "Primary cause(s) with evidence.",
                "timeline": "Chronological list of key events with timestamps.",
                "corrective_actions": "Concrete fixes with owners and due dates.",
                "prevention": "Longer-term hardening and monitoring steps.",
            },
            "guidance": "Keep tone blameless; focus on evidence and owned actions.",
        },
        "comparison": {
            "format": "comparison_v1",
            "description": "Side-by-side comparison with scored criteria",
            "sections": [
                "subject",
                "criteria",
                "scorecard",
                "recommendation",
                "risks",
            ],
            "section_schemas": {
                "subject": "What is being compared and the decision to be made.",
                "criteria": "Evaluation criteria with weights or importance.",
                "scorecard": "Table or bullets scoring options against criteria.",
                "recommendation": "Clear pick with rationale tied to criteria.",
                "risks": "Caveats, migration cost, or follow-up checks.",
            },
            "guidance": "Lead with the recommendation; keep scoring transparent.",
        },
    }

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def resolve_method_key(self, task_type: str) -> str:
        if task_type in self.METHOD_DEFINITIONS:
            return task_type
        fallback_map = {
            "qa": "qa",
            "faq": "qa",
            "cheatsheet": "cheatsheet",
            "cheat_sheet": "cheatsheet",
            "howto": "tutorial",
            "how_to": "tutorial",
            "troubleshoot": "troubleshooting",
            "reference_sheet": "reference",
            "plan": "project_plan",
            "project": "project_plan",
            "study": "study_guide",
            "design": "design_doc",
            "architecture": "design_doc",
            "adr": "design_doc",
            "post_mortem": "postmortem",
            "incident_review": "postmortem",
            "retro": "postmortem",
            "versus": "comparison",
            "vs": "comparison",
            "compare": "comparison",
        }
        return fallback_map.get(task_type, "lesson_page")

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
                heading_parts = re.split(r"\s*[:\-–—]\s*", heading_text, 1)
                heading_core = heading_parts[0]
                descriptor_text = heading_parts[1].strip() if len(heading_parts) > 1 else ""

                heading_core = re.split(r"\s*[:\-–—]\s*", heading_core, 1)[0]
                heading_core = re.split(r"[.!?]", heading_core, 1)[0]
                heading_core = heading_core.rstrip(" .,:;–—-").strip()
                normalized_heading = self._normalize(heading_core)
                key = normalized_required.get(normalized_heading)
                if current:
                    content_map[current] = "\n".join(buffer).strip()
                current = key if key else None
                buffer = []
                if current and descriptor_text:
                    buffer.append(descriptor_text)
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
        guidance = method_def.get("guidance", "")
        example_blocks = method_def.get("examples", [])
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

        examples_help = "\n".join(str(block).strip("\n") for block in example_blocks)

        return (
            "You are MetodiAgentti followed by TuottajaAgentti. Use the provided method to build content.\n"
            f"Task type: {task_spec.task_type} ({method_def['description']}).\n"
            f"Method: {method_def['format']} with sections {sections}.\n"
            f"Section schema:\n{section_help}\n"
            f"Intent: topic={task_spec.topic}, language={task_spec.language}, target_level={task_spec.target_level}.\n"
            f"{constraints_line}"
            f"{heading_help}\n"
            f"Guidance: {guidance}\n"
            f"Examples (structure, not verbatim to copy):\n{examples_help}\n"
            "Return the content labeled per section in Markdown."
        )

    def _compute_revision_delta(
        self, sections_content: Dict[str, str], previous_sections: Dict[str, str] | None
    ) -> Dict[str, List[str]]:
        previous_sections = previous_sections or {}
        added = [section for section in sections_content if section not in previous_sections]
        changed = [
            section
            for section, body in sections_content.items()
            if section in previous_sections and body.strip() != previous_sections.get(section, "").strip()
        ]
        return {"added_sections": added, "changed_sections": changed}

    def run(
        self,
        run_id: str,
        task_spec: TaskSpec,
        prior_review: ReviewReport | None = None,
        revision_number: int = 0,
        method_key: str | None = None,
        previous_sections: Dict[str, str] | None = None,
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
        revision_delta = self._compute_revision_delta(sections_content, previous_sections)

        method_respected = len(missing_sections) == 0
        warnings: List[str] = []
        if missing_sections:
            warnings.append(f"Missing sections: {', '.join(missing_sections)}")

        content = {"format": method_plan.format, **sections_content, "raw": generated}
        if revision_number > 0:
            content["revision_note"] = f"Revision #{revision_number} applied"

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
