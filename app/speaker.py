from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from typing import Dict

from app.agents.shadow import ShadowAgent
from app.circuits.intent import IntentContextCircuit
from app.circuits.method import MethodProducerCircuit
from app.circuits.review import ReviewJudgeCircuit
from app.models import CircuitResult, Message, TaskSpec, UserResponse
from app.utils.llm_client import LLMClient


class SpeakerAgent:
    def __init__(self, llm: LLMClient, shadow_agent: ShadowAgent) -> None:
        self.llm = llm
        self.shadow = shadow_agent
        self.intent_circuit = IntentContextCircuit(llm)
        self.method_circuit = MethodProducerCircuit(llm)
        self.review_circuit = ReviewJudgeCircuit()
        try:
            configured_revisions = int(os.getenv("MAX_REVISIONS", "2"))
        except ValueError:
            configured_revisions = 2
        self.max_revisions = max(0, configured_revisions)

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def _record(self, message: Message) -> None:
        self.shadow.observe(message)

    def process(self, user_message: str) -> CircuitResult:
        run_id = self.new_run_id()

        self._record(
            Message(
                run_id=run_id,
                sender="User",
                recipient="PuhemiesAgentti",
                role="instruction",
                payload={"message": user_message},
            )
        )

        intent_result = self.intent_circuit.run(run_id, user_message)
        intent_message = intent_result["message"]
        task_spec: TaskSpec = intent_result["task_spec"]
        self._record(intent_message)

        revision_count = 0
        method_result = self.method_circuit.run(run_id, task_spec)
        method_message = method_result["message"]
        method_plan = method_result["method_plan"]
        content_package = method_result["content_package"]
        self._record(method_message)

        review_result = self.review_circuit.run(run_id, method_plan, content_package)
        review_message = review_result["message"]
        review = review_result["review"]
        decision = review_result["decision"]
        self._record(review_message)

        while decision.decision == "revise" and revision_count < self.max_revisions:
            revision_count += 1
            revision_instruction = Message(
                run_id=run_id,
                sender="PuhemiesAgentti",
                recipient="MetodiPiiri",
                role="instruction",
                payload={
                    "reason": decision.reason,
                    "missing_sections": review.missing_sections,
                    "revision": revision_count,
                },
            )
            self._record(revision_instruction)

            method_result = self.method_circuit.run(
                run_id,
                task_spec,
                prior_review=review,
                revision_number=revision_count,
            )
            method_message = method_result["message"]
            method_plan = method_result["method_plan"]
            content_package = method_result["content_package"]
            self._record(method_message)

            review_result = self.review_circuit.run(run_id, method_plan, content_package)
            review_message = review_result["message"]
            review = review_result["review"]
            decision = review_result["decision"]
            self._record(review_message)

        self._record(
            Message(
                run_id=run_id,
                sender="PuhemiesAgentti",
                recipient="User",
                role="summary",
                payload={"decision": decision.decision, "reason": decision.reason},
            )
        )

        shadow_report = self.shadow.summarize(run_id, review, method_plan, content_package)

        return CircuitResult(
            task_spec=task_spec,
            method_plan=method_plan,
            content=content_package,
            review=review,
            decision=decision,
            shadow_report=shadow_report,
        )

    def build_user_response(self, result: CircuitResult) -> UserResponse:
        summary = (
            f"{result.decision.decision.upper()} — drift_score: {result.shadow_report.get('drift_score')}"
            f" — revisions: {result.content.revision_number}"
        )
        return UserResponse(
            run_id=result.task_spec.run_id,
            decision=result.decision.decision,
            summary=summary,
            content=result.content.content,
            shadow_report_path=str(self.shadow.storage_path),
        )

    def process_and_summarize(self, user_message: str) -> Dict[str, object]:
        result = self.process(user_message)
        response = self.build_user_response(result)
        return {"response": asdict(response), "details": asdict(result)}
