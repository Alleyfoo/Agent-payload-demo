from __future__ import annotations

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

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def _record(self, message: Message) -> None:
        self.shadow.observe(message)

    def process(self, user_message: str) -> CircuitResult:
        run_id = self.new_run_id()

        intent_result = self.intent_circuit.run(run_id, user_message)
        intent_message = intent_result["message"]
        task_spec: TaskSpec = intent_result["task_spec"]
        self._record(intent_message)

        method_key = self.method_circuit.resolve_method_key(task_spec.task_type)
        method_result = self.method_circuit.run(run_id, task_spec, method_key)
        method_message = method_result["message"]
        method_plan = method_result["method_plan"]
        content_package = method_result["content_package"]
        self._record(method_message)

        for revision in range(max_revisions):
            method_result = self.method_circuit.run(
                run_id, task_spec, revision_index=revision, previous_sections=previous_sections
            )
            method_message = method_result["message"]
            method_plan = method_result["method_plan"]
            content_package = method_result["content_package"]
            revision_delta = method_result["revision_delta"]
            revision_history.append(revision_delta)
            content_package.revision_history = list(revision_history)
            self._record(method_message)

            review_result = self.review_circuit.run(run_id, method_plan, content_package)
            review_message = review_result["message"]
            review = review_result["review"]
            decision = review_result["decision"]
            self._record(review_message)

            previous_sections = method_result["sections_content"]

            if decision.decision == "accept":
                break

        shadow_report = self.shadow.summarize(run_id, review, revision_history)

        return CircuitResult(
            task_spec=task_spec,
            method_plan=method_plan,
            content=content_package,
            review=review,
            decision=decision,
            shadow_report=shadow_report,
        )

    def build_user_response(self, result: CircuitResult) -> UserResponse:
        revision_history = result.content.revision_history
        latest_delta = revision_history[-1] if revision_history else {}
        summary = (
            f"{result.decision.decision.upper()} — revisions: {len(revision_history)}; "
            f"added: {latest_delta.get('added_sections', [])}; "
            f"changed: {latest_delta.get('changed_sections', [])}; "
            f"drift_score: {result.shadow_report.get('drift_score')}"
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
