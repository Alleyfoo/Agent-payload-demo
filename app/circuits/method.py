from __future__ import annotations

from typing import Dict

from app.models import ContentPackage, Message, MethodPlan, TaskSpec
from app.utils.llm_client import LLMClient


class MethodProducerCircuit:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, run_id: str, task_spec: TaskSpec) -> Dict[str, MethodPlan | ContentPackage | Message]:
        method_plan = MethodPlan(format="lesson_v1", sections=["title", "concept", "code_example", "exercise"])
        prompt = (
            "You are MetodiAgentti followed by TuottajaAgentti. Use the provided method to build content.\n"
            f"Method: {method_plan.format} with sections {method_plan.sections}.\n"
            f"Intent: topic={task_spec.topic}, language={task_spec.language}, target_level={task_spec.target_level}.\n"
            "Return the content labeled per section in Markdown."
        )
        generated = self.llm.generate(prompt)

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
        )

        message = Message(
            run_id=run_id,
            sender="PuhemiesAgentti",
            recipient="MetodiPiiri",
            role="result",
            payload={"method": method_plan.format, "sections": method_plan.sections, "content": generated},
        )
        return {"method_plan": method_plan, "content_package": package, "message": message}
