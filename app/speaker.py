from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from typing import Dict, List

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

        method_key = self.method_circuit.resolve_method_key(task_spec.task_type)
        revision_history: List[Dict[str, object]] = []
        previous_sections: Dict[str, str] = {}
        review = None
        decision = None
        method_plan = None
        content_package = None

        for revision in range(self.max_revisions + 1):
            method_result = self.method_circuit.run(
                run_id,
                task_spec,
                prior_review=review,
                revision_number=revision,
                method_key=method_key,
                previous_sections=previous_sections,
            )
            method_message = method_result["message"]
            method_plan = method_result["method_plan"]
            content_package = method_result["content_package"]
            revision_delta = {"revision": revision, **method_result["revision_delta"]}
            revision_history.append(revision_delta)
            content_package.revision_history = list(revision_history)
            content_package.revision_number = revision
            content_package.content["revision_history"] = list(revision_history)
            self._record(method_message)

            review_result = self.review_circuit.run(run_id, method_plan, content_package)
            review_message = review_result["message"]
            review = review_result["review"]
            decision = review_result["decision"]
            self._record(review_message)

            previous_sections = method_result["sections_content"]
            if decision.decision != "revise":
                break

        self._record(
            Message(
                run_id=run_id,
                sender="PuhemiesAgentti",
                recipient="User",
                role="summary",
                payload={
                    "decision": decision.decision if decision else "unknown",
                    "reason": decision.reason if decision else "",
                    "revisions": revision_history,
                },
            )
        )

        shadow_report = self.shadow.summarize(
            run_id,
            review,  # type: ignore[arg-type]
            method_plan,  # type: ignore[arg-type]
            content_package,  # type: ignore[arg-type]
            revision_history,
            decision,
        )

        return CircuitResult(
            task_spec=task_spec,
            method_plan=method_plan,  # type: ignore[arg-type]
            content=content_package,  # type: ignore[arg-type]
            review=review,  # type: ignore[arg-type]
            decision=decision,  # type: ignore[arg-type]
            shadow_report=shadow_report,
        )

    def build_user_response(self, result: CircuitResult) -> UserResponse:
        revision_history = result.content.revision_history
        latest_delta = revision_history[-1] if revision_history else {}
        summary = (
            f"{result.decision.decision.upper()} — total revisions: {len(revision_history)}; "
            f"latest added: {latest_delta.get('added_sections', [])}; "
            f"latest changed: {latest_delta.get('changed_sections', [])}; "
            f"drift_score: {result.shadow_report.get('drift_score')}; "
            f"section_completion: {result.shadow_report.get('section_completion_rate')}"
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
