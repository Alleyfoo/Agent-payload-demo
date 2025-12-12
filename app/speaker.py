from __future__ import annotations

import os
import uuid
import re
import json
from dataclasses import asdict
from typing import Dict, List, Any

from app.agents.shadow import ShadowAgent
from app.breathing import default_params
from app.checkup_layer import build_evaluation_contract
from app.circuits.context import ContextStateCircuit
from app.circuits.hybrid import (
    HealingComposer,
    BuddhistStabilizerCircuit,
    GroundingCircuit,
    SelfishBuddhistCircuit,
    SelfishComposer,
    PuhemiesClassifier,
    TaoistIntentCircuit,
)
from app.circuits.intent import IntentContextCircuit
from app.circuits.method import MethodProducerCircuit
from app.circuits.review import ReviewJudgeCircuit
from app.circuits.patch_resolver import PatchResolverCircuit
from app.models import (
    BuddhistResponse,
    CandidateOutput,
    CandidateScores,
    CircuitResult,
    EnergyVector,
    GroundingPlan,
    HexagramState,
    Message,
    PuhemiesHeader,
    TaskSpec,
    TaoistIntent,
    UserResponse,
    Verdict,
)
from app.patch_detector import PatchDetector
from app.regulator import CompassionateRegulator
from app.utils.llm_client import LLMClient


class SpeakerAgent:
    def __init__(self, llm: LLMClient, shadow_agent: ShadowAgent) -> None:
        self.llm = llm
        self.shadow = shadow_agent
        self.intent_circuit = IntentContextCircuit(llm)
        self.method_circuit = MethodProducerCircuit(llm)
        self.review_circuit = ReviewJudgeCircuit()
        self.taoist_circuit = TaoistIntentCircuit(llm)
        self.buddhist_circuit = BuddhistStabilizerCircuit(llm)
        self.selfish_circuit = SelfishBuddhistCircuit(llm)
        self.healing_composer = HealingComposer(llm)
        self.selfish_composer = SelfishComposer(llm)
        self.classifier = PuhemiesClassifier()
        self.grounding = GroundingCircuit()
        self.context_state = ContextStateCircuit()
        self.patch_detector = PatchDetector()
        self.patch_resolver = PatchResolverCircuit(normalizer=self._normalize_fastener_rows)
        self.agent_params = default_params()
        self.regulator = CompassionateRegulator(self.agent_params)
        try:
            configured_revisions = int(os.getenv("MAX_REVISIONS", "2"))
        except ValueError:
            configured_revisions = 2
        self.max_revisions = max(0, configured_revisions)

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def _record(self, message: Message) -> None:
        self.shadow.observe(message)

    def _firewall(self, text: str) -> str:
        patterns = [
            r"task type[:=].*",
            r"required grounding[:=].*",
            r"breathing params?:.*",
            r"hexagram[:=].*",
            r"intent[:=].*",
            r"notes: taoist intent.*",
            r"as a buddhist.*",
            r"as a (?:selfish|baseline).*",
            r"remember to breathe.*",
        ]
        cleaned = text
        for pat in patterns:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _apply_task_type_override(self, header: PuhemiesHeader, task_type: str) -> PuhemiesHeader:
        """Allow UI to force a task type while keeping other header defaults stable."""
        override = task_type.strip()
        if not override:
            return header
        header.task_type = override
        header.required_grounding = override == "weather_lookup"
        if not header.user_intent or header.user_intent.lower() == "general request":
            header.user_intent = f"User-selected: {override}"
        note_suffix = "Task type overridden by user selection."
        header.notes = f"{header.notes} | {note_suffix}" if header.notes else note_suffix
        return header

    def _extract_json_artifact(self, text: str) -> Any | None:
        blocks = re.findall(r"```json(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if not blocks:
            blocks = re.findall(r"\[(?:.|\n)*\]", text)
        for blk in blocks:
            try:
                data = json.loads(blk.strip())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue
        return None

    def _normalize_fastener_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        COATING = {"zp", "zn", "zinc", "hdg", "dacromet", "geomet", "plain"}
        MATERIAL = {"a2", "a4", "ss", "stainless"}
        def classify_token(token: str) -> str | None:
            t = token.lower()
            if t in COATING:
                return "coating"
            if t in MATERIAL:
                return "material"
            if re.match(r"^\d+\.\d+$", t):
                return "grade"
            return None

        for row in rows:
            for key in list(row.keys()):
                val = row.get(key)
                if not isinstance(val, str):
                    continue
                parts = re.split(r"[ ,/]+", val)
                for p in parts:
                    cls = classify_token(p)
                    if cls == "coating":
                        row["coating"] = row.get("coating") or p
                        if row.get(key) == p:
                            row[key] = None
                    elif cls == "material":
                        row["material"] = row.get("material") or p
                        if row.get(key) == p:
                            row[key] = None
                    elif cls == "grade":
                        row["grade"] = row.get("grade") or p
                        if row.get(key) == p:
                            row[key] = None
        return rows

    def _parse_lines_to_artifact(self, user_message: str) -> List[Dict[str, Any]] | None:
        lines = [ln.strip() for ln in user_message.splitlines() if ln.strip()]
        artifact: List[Dict[str, Any]] = []
        for ln in lines:
            if not re.search(r"(DIN|ISO)", ln, re.IGNORECASE):
                continue
            tokens = ln.split()
            std_match = re.search(r"(DIN\s*\d+[A-Z\-]*|DIN\d+[A-Z\-]*|ISO\s*\d+|ISO\d+)", ln, re.IGNORECASE)
            if not std_match:
                continue
            standard_raw = std_match.group(1)
            standard = standard_raw.replace("DIN", "DIN ").replace("ISO", "ISO ").replace("  ", " ").strip()
            msize = re.search(r"M(\d+)(x(\d+))?", ln, re.IGNORECASE)
            size = None
            length = None
            if msize:
                size = f"M{msize.group(1)}"
                if msize.group(3):
                    try:
                        length = int(msize.group(3))
                    except ValueError:
                        length = None
            material = None
            coating = None
            # map tokens
            if re.search(r"\bA2\b", ln, re.IGNORECASE):
                material = "stainless A2"
            elif re.search(r"\bA4\b", ln, re.IGNORECASE):
                material = "stainless A4"
            if re.search(r"\bZP\b", ln, re.IGNORECASE) or re.search(r"\bZnPl\b", ln, re.IGNORECASE) or re.search(r"\bZn\b", ln, re.IGNORECASE):
                coating = "zinc plated"

            artifact.append(
                {
                    "standard": standard,
                    "size": size,
                    "length": length,
                    "material": material,
                    "coating": coating,
                }
            )
        return artifact if artifact else None

    def _apply_mappings(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for row in rows:
            mat = row.get("material")
            coat = row.get("coating")
            if isinstance(mat, str) and mat.lower() == "a2":
                row["material"] = "stainless A2"
            if isinstance(mat, str) and mat.lower() == "a4":
                row["material"] = "stainless A4"
            if isinstance(coat, str) and coat.lower() in {"zp", "zn", "znpl", "zinc"}:
                row["coating"] = "zinc plated"
            # also if coating is None but tokens linger in other fields
            for key, val in list(row.items()):
                if isinstance(val, str):
                    if val.lower() in {"zp", "zn", "znpl", "zinc"}:
                        row["coating"] = "zinc plated"
                        if key != "coating":
                            row[key] = None
                    if val.lower() in {"a2", "stainless a2"}:
                        row["material"] = "stainless A2"
                        if key != "material":
                            row[key] = None
                    if val.lower() in {"a4", "stainless a4"}:
                        row["material"] = "stainless A4"
                        if key != "material":
                            row[key] = None
        return rows

    def _validate_schema(self, data: Any, expected_keys: List[str] | None = None) -> bool:
        if not isinstance(data, list) or not data:
            return False
        for row in data:
            if not isinstance(row, dict):
                return False
            if expected_keys and set(row.keys()) != set(expected_keys):
                return False
        return True

    def _validate_schema(self, data: Any, expected_keys: List[str] | None = None) -> bool:
        if not isinstance(data, list) or not data:
            return False
        for row in data:
            if not isinstance(row, dict):
                return False
            if expected_keys and set(row.keys()) != set(expected_keys):
                return False
        return True

    # Original single-path pipeline (Intent -> Method -> Review)
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
        method_name = result.method_plan.format
        resolved_task_type = self.method_circuit.resolve_method_key(result.task_spec.task_type)
        summary = (
            f"{result.decision.decision.upper()} total revisions: {len(revision_history)}; "
            f"latest added: {latest_delta.get('added_sections', [])}; "
            f"latest changed: {latest_delta.get('changed_sections', [])}; "
            f"method: {method_name} (task_type: {resolved_task_type}); "
            f"drift_score: {result.shadow_report.get('drift_score')}; "
            f"section_completion: {result.shadow_report.get('section_completion_rate')}"
        )
        revision_summary = {
            "method": method_name,
            "task_type": resolved_task_type,
            "revision_history": revision_history,
        }
        return UserResponse(
            run_id=result.task_spec.run_id,
            decision=result.decision.decision,
            summary=summary,
            content=result.content.content,
            shadow_report_path=str(self.shadow.storage_path),
            revision_summary=revision_summary,
        )

    def process_and_summarize(self, user_message: str) -> Dict[str, object]:
        result = self.process(user_message)
        response = self.build_user_response(result)
        return {"response": asdict(response), "details": asdict(result)}

    # Dual-path pipeline (Taoist -> healing + selfish) with comparison
    def process_dual_paths(
        self,
        user_message: str,
        energy: EnergyVector | None = None,
        hexagram_id: int | None = None,
    ) -> Dict[str, object]:
        run_id = self.new_run_id()
        energy_vec = energy or EnergyVector.infer(user_message)
        hexagram = HexagramState(hexagram_id, name="unspecified" if hexagram_id else "neutral")

        self._record(
            Message(
                run_id=run_id,
                sender="User",
                recipient="PuhemiesAgentti",
                role="instruction",
                payload={
                    "message": user_message,
                    "energy": energy_vec.as_dict(),
                    "hexagram": hexagram.label(),
                },
            )
        )

        taoist_result = self.taoist_circuit.run(run_id, user_message, energy_vec, hexagram)
        taoist_intent: TaoistIntent = taoist_result.intent
        self._record(taoist_result.message)

        healing_result = self.buddhist_circuit.run(run_id, user_message, taoist_intent, energy_vec, hexagram)
        healing_response: BuddhistResponse = healing_result.response
        self._record(healing_result.message)

        selfish_result = self.selfish_circuit.run(run_id, user_message, taoist_intent, energy_vec, hexagram)
        selfish_response: BuddhistResponse = selfish_result.response
        self._record(selfish_result.message)

        comparison = self.shadow.compare_outputs(
            run_id,
            [
                {"label": "healing", "role": "buddhist_shell", "text": healing_response.content},
                {"label": "selfish", "role": "selfish_shell", "text": selfish_response.content},
            ],
        )

        self._record(
            Message(
                run_id=run_id,
                sender="PuhemiesAgentti",
                recipient="User",
                role="summary",
                payload={
                    "taoist_intent": taoist_intent.intent,
                    "healing": healing_response.content,
                    "selfish": selfish_response.content,
                    "verdict": comparison.get("verdict"),
                },
            )
        )

        return {
            "run_id": run_id,
            "taoist_intent": taoist_intent.intent,
            "healing_response": healing_response.content,
            "selfish_response": selfish_response.content,
            "verdict": comparison.get("verdict"),
            "comparison": comparison,
            "shadow_report_path": str(self.shadow.storage_path),
        }

    # Full hierarchical chain per spec: Puhemies -> Taoist -> Grounding -> Healing/Selfish -> Judge
    def process_hierarchical(
        self,
        user_message: str,
        energy: EnergyVector | None = None,
        hexagram_id: int | None = None,
        task_type: str | None = None,
    ) -> Dict[str, object]:
        run_id = self.new_run_id()
        energy_vec = energy or EnergyVector.infer(user_message)
        hexagram = HexagramState(hexagram_id, name="unspecified" if hexagram_id else "neutral")

        # Step 1: Puhemies classification
        header: PuhemiesHeader = self.classifier.classify(user_message)
        if task_type:
            header = self._apply_task_type_override(header, task_type)
        self._record(
            Message(
                run_id=run_id,
                sender="User",
                recipient="PuhemiesAgentti",
                role="instruction",
                payload={"message": user_message, "energy": energy_vec.as_dict(), "hexagram": hexagram.label(), "header": header.__dict__},
            )
        )

        # Step 2: Taoist intent
        taoist_result = self.taoist_circuit.run(run_id, user_message, energy_vec, hexagram)
        taoist_intent: TaoistIntent = taoist_result.intent
        self._record(taoist_result.message)

        # Step 3: Grounding plan
        grounding_plan: GroundingPlan = self.grounding.plan(header, taoist_intent)
        self._record(
            Message(
                run_id=run_id,
                sender="GroundingCircuit",
                recipient="PuhemiesAgentti",
                role="grounding_plan",
                payload={"grounding": grounding_plan.__dict__, "header": header.__dict__},
            )
        )

        # Step 4: Healing candidate
        healing_result = self.healing_composer.run(
            run_id,
            user_message,
            header,
            taoist_intent,
            grounding_plan,
            breathing=self.agent_params.get("healing", None).as_dict() if self.agent_params.get("healing") else None,
        )
        healing_response: BuddhistResponse = healing_result.response
        healing_response.content = self._firewall(healing_response.content)
        self._record(healing_result.message)
        artifact = self._extract_json_artifact(healing_response.content)
        if artifact:
            if isinstance(artifact, list) and artifact and isinstance(artifact[0], dict):
                artifact = self._normalize_fastener_rows(artifact)
            schema = {}
            if isinstance(artifact, list) and artifact and isinstance(artifact[0], dict):
                schema = {k: "unknown" for k in artifact[0].keys()}
            self.context_state.set_artifact(artifact, artifact_type="extraction_result", schema=schema)
        else:
            # Attempt a constrained regeneration for extraction tasks
            if header.task_type in ("data_extraction", "math") or "output json" in user_message.lower():
                regen_constraints = [
                    "Output ONLY the JSON array with objects containing fields: standard, size, length, material, coating.",
                    "No prose or markdown fences.",
                ]
                healing_result = self.healing_composer.run(
                    run_id,
                    user_message,
                    header,
                    taoist_intent,
                    grounding_plan,
                    breathing=self.agent_params.get("healing", None).as_dict() if self.agent_params.get("healing") else None,
                    constraints=regen_constraints,
                )
                healing_response = healing_result.response
                healing_response.content = self._firewall(healing_response.content)
                self._record(healing_result.message)
                artifact = self._extract_json_artifact(healing_response.content)
                if artifact:
                    if isinstance(artifact, list) and artifact and isinstance(artifact[0], dict):
                        artifact = self._normalize_fastener_rows(artifact)
                    schema = {}
                    if isinstance(artifact, list) and artifact and isinstance(artifact[0], dict):
                        schema = {k: "unknown" for k in artifact[0].keys()}
                    self.context_state.set_artifact(artifact, artifact_type="extraction_result", schema=schema)

        # Step 5: Selfish candidate
        selfish_result = self.selfish_composer.run(
            run_id,
            user_message,
            header,
            taoist_intent,
            grounding_plan,
            breathing=self.agent_params.get("selfish", None).as_dict() if self.agent_params.get("selfish") else None,
        )
        selfish_response: BuddhistResponse = selfish_result.response
        selfish_response.content = self._firewall(selfish_response.content)
        self._record(selfish_result.message)

        patch_info = self.patch_detector.detect(user_message)
        patch_needs_artifact = patch_info.get("needs_artifact", False) and not self.context_state.has_artifact()

        # If patch requested and we have an artifact, apply it deterministically
        if patch_info.get("is_patch") and self.context_state.has_artifact():
            state = self.context_state.get_state()
            result = self.patch_resolver.apply_patch(user_message, state.active_artifact)
            if result.updated_artifact is not None:
                updated_artifact = result.updated_artifact
                schema = {}
                if isinstance(updated_artifact, list) and updated_artifact and isinstance(updated_artifact[0], dict):
                    schema = {k: "unknown" for k in updated_artifact[0].keys()}
                self.context_state.set_artifact(updated_artifact, artifact_type=state.artifact_type or "extraction_result", schema=schema)
                healing_response.content = self._firewall(result.rendered)

        # Checkup contract (dynamic rubric/gates)
        contract_obj = build_evaluation_contract(
            user_message=user_message,
            header=header,
            taoist_intent=taoist_intent,
            candidates=[
                {"agent_id": "healing", "text": healing_response.content},
                {"agent_id": "selfish", "text": selfish_response.content},
            ],
            patch_needs_artifact=patch_needs_artifact,
            patch_is_patch=bool(patch_info.get("is_patch")),
        )
        contract_dict = {
            "task_summary": contract_obj.task_summary,
            "deliverables": [d.__dict__ for d in contract_obj.deliverables],
            "truth_critical": contract_obj.truth_critical,
            "needs_external_grounding": contract_obj.needs_external_grounding,
            "rubric": contract_obj.rubric,
            "hard_gates": contract_obj.hard_gates,
            "target_expression": contract_obj.target_expression,
            "expected_result": contract_obj.expected_result,
            "patch_requires_artifact": contract_obj.patch_requires_artifact,
            "patch_requires_render": contract_obj.patch_requires_render,
            "pipeline_required": contract_obj.pipeline_required,
            "crypto_sanity_required": contract_obj.crypto_sanity_required,
            "math_list_required": contract_obj.math_list_required,
            "extraction_required": contract_obj.extraction_required,
            "math_expected_mean": contract_obj.math_expected_mean,
            "math_expected_median": contract_obj.math_expected_median,
            "strict_numeric_truth": contract_obj.strict_numeric_truth,
            "tip_domain_required": contract_obj.tip_domain_required,
            "expected_schema": contract_obj.expected_schema,
        }

        # Step 6: Shadow judge (verdict)
        comparison = self.shadow.compare_outputs(
            run_id,
            [
                {"label": "healing", "role": "healing_shell", "text": healing_response.content, "header": header.__dict__},
                {"label": "selfish", "role": "selfish_shell", "text": selfish_response.content, "header": header.__dict__},
            ],
            required_grounding=header.required_grounding,
            contract=contract_dict,
            prune=False,
        )

        # compassionate regulator: adjust underperformer, optional retry once
        regulation_info: Dict[str, object] | None = None
        regulation = self.regulator.regulate(
            Verdict(
                winner=comparison.get("winner", ""),
                scores={
                    aid: CandidateScores(
                        correctness=score.get("correctness", 0),
                        truth=score.get("truth", 0),
                        task_fit=score.get("task_fit", 0),
                        clarity=score.get("clarity", 0),
                        tone=score.get("tone", 0),
                        safety=str(score.get("safety", "pass")),
                        utility=score.get("utility", 0),
                    )
                    for aid, score in comparison.get("scores", {}).items()
                },
                reason=comparison.get("verdict", ""),
                confidence=float(comparison.get("confidence", 0.8)),
                ranked=comparison.get("ranked", []),
                issues=comparison.get("issues", {}),
                required_grounding=header.required_grounding,
                gate_violations=comparison.get("gate_violations", {}),
            ),
            required_grounding=header.required_grounding,
            contract=contract_dict,
        )

        before_text = {"healing": healing_response.content, "selfish": selfish_response.content}

        if regulation and regulation.retry:
            if regulation.agent_id == "healing":
                healing_result = self.healing_composer.run(
                    run_id,
                    user_message,
                    header,
                    taoist_intent,
                    grounding_plan,
                    breathing=self.agent_params.get("healing", None).as_dict() if self.agent_params.get("healing") else None,
                    constraints=regulation.behavioral_constraints,
                )
                healing_response = healing_result.response
                healing_response.content = self._firewall(healing_response.content)
                self._record(healing_result.message)
            elif regulation.agent_id == "selfish":
                selfish_result = self.selfish_composer.run(
                    run_id,
                    user_message,
                    header,
                    taoist_intent,
                    grounding_plan,
                    breathing=self.agent_params.get("selfish", None).as_dict() if self.agent_params.get("selfish") else None,
                    constraints=regulation.behavioral_constraints,
                )
                selfish_response = selfish_result.response
                selfish_response.content = self._firewall(selfish_response.content)
                self._record(selfish_result.message)

            comparison = self.shadow.compare_outputs(
                run_id,
                [
                    {"label": "healing", "role": "healing_shell", "text": healing_response.content, "header": header.__dict__},
                    {"label": "selfish", "role": "selfish_shell", "text": selfish_response.content, "header": header.__dict__},
                ],
                required_grounding=header.required_grounding,
                contract=contract_dict,
                prune=False,
            )
            regulation_info = {
                "agent_id": regulation.agent_id,
                "intervention": regulation.intervention,
                "parameter_deltas": regulation.parameter_deltas,
                "constraints": regulation.behavioral_constraints,
                "before": before_text.get(regulation.agent_id, ""),
                "after": healing_response.content if regulation.agent_id == "healing" else selfish_response.content,
            }
            self._record(
                Message(
                    run_id=run_id,
                    sender="CompassionateRegulator",
                    recipient=regulation.agent_id,
                    role="regulation",
                    payload=regulation_info,
                )
            )

        # Shadow verdict message for trace
        self._record(
            Message(
                run_id=run_id,
                sender="ShadowJudge",
                recipient="PuhemiesAgentti",
                role="verdict",
                payload={"verdict": comparison.get("verdict"), "winner": comparison.get("winner"), "issues": comparison.get("issues")},
            )
        )

        # prune messages after all comparisons
        self.shadow.prune_run(run_id)

        # Summarize to user
        self._record(
            Message(
                run_id=run_id,
                sender="PuhemiesAgentti",
                recipient="User",
                role="summary",
                payload={
                    "header": header.__dict__,
                    "taoist_intent": taoist_intent.intent,
                    "grounding": grounding_plan.__dict__,
                    "healing": healing_response.content,
                    "selfish": selfish_response.content,
                    "verdict": comparison.get("verdict"),
                    "regulation": regulation_info or (regulation.__dict__ if regulation else {}),
                },
            )
        )

        return {
            "run_id": run_id,
            "header": header.__dict__,
            "taoist_intent": taoist_intent.intent,
            "grounding": grounding_plan.__dict__,
            "healing_response": healing_response.content,
            "selfish_response": selfish_response.content,
            "verdict": comparison.get("verdict"),
            "alternatives": comparison.get("alternatives"),
            "regulation": regulation_info or (regulation.__dict__ if regulation else {}),
            "shadow_report_path": str(self.shadow.storage_path),
        }
