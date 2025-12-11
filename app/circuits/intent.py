from __future__ import annotations

import json
from typing import Dict

from app.models import Message, TaskSpec
from app.utils.llm_client import LLMClient


class IntentContextCircuit:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, run_id: str, user_message: str) -> Dict[str, Message | TaskSpec]:
        prompt = (
            "You are IntentioAgentti + KontekstiAgentti working together. "
            "Create a structured JSON description of the user's goal. "
            "Fields: task_type, topic, language, target_level, constraints, status."
            f"User message: {user_message}\nRespond with JSON only."
        )
        raw = self.llm.generate(prompt)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {
                "task_type": "lesson_page",
                "topic": user_message[:60] or "general_topic",
                "language": "fi",
                "target_level": "beginner",
                "constraints": ["markdown output"],
                "status": "needs_clarification",
            }

        task_spec = TaskSpec(
            run_id=run_id,
            task_type=payload.get("task_type", "lesson_page"),
            topic=payload.get("topic", "general_topic"),
            language=payload.get("language", "fi"),
            target_level=payload.get("target_level", "beginner"),
            constraints=payload.get("constraints", ["markdown output"]),
            status=payload.get("status", "ok"),
        )

        message = Message(
            run_id=run_id,
            sender="PuhemiesAgentti",
            recipient="IntentioPiiri",
            role="result",
            payload=payload,
        )
        return {"message": message, "task_spec": task_spec}
