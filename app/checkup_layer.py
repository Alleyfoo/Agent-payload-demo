from __future__ import annotations

import re
from typing import Dict, List

from app.models import Deliverable, EvaluationContract, PuhemiesHeader, TaoistIntent


def _detect_deliverables(user_message: str) -> List[Deliverable]:
    text = user_message.lower()
    deliverables: List[Deliverable] = []
    if any(token in text for token in ["compute", "calculate", "count", "multiply", "divide", "sqrt", "square root", "product"]):
        deliverables.append(Deliverable(type="result", description="Provide the computed answer", count=1))

    advice_match = re.search(r"(\d+)\s+(tips|advices|advice|ways|methods)", text)
    if advice_match:
        count = int(advice_match.group(1))
        deliverables.append(Deliverable(type="advice", description="Give concrete tips", count=count))
    elif any(token in text for token in ["tip", "advice", "suggestion"]):
        deliverables.append(Deliverable(type="advice", description="Give concrete tips", count=2))
    return deliverables


def _truth_criticality(deliverables: List[Deliverable]) -> str:
    if any(d.type == "result" for d in deliverables):
        return "high"
    return "medium"


def _needs_grounding(header: PuhemiesHeader, user_message: str) -> str:
    text = user_message.lower()
    if header.required_grounding:
        return "high"
    if "current" in text and any(token in text for token in ["rate", "price", "weather", "temperature"]):
        return "high"
    return "low"


def _extract_target_expression(user_message: str) -> Dict[str, object]:
    text = user_message
    expr_match = re.search(r"(\d+)\s*[*xX]\s*(\d+)", text)
    if expr_match:
        a = int(expr_match.group(1))
        b = int(expr_match.group(2))
        return {"expression": f"{a}*{b}", "expected_result": a * b}
    expr_match = re.search(r"(\d+)\s+times\s+(\d+)", text.lower())
    if expr_match:
        a = int(expr_match.group(1))
        b = int(expr_match.group(2))
        return {"expression": f"{a}*{b}", "expected_result": a * b}
    return {}


def _looks_like_pipeline_request(user_message: str) -> bool:
    text = user_message.lower()
    return any(token in text for token in ["pipeline", "steps", "design a pipeline", "merge two csv", "process steps", "plan steps"])


def _mentions_reversible_hash(user_message: str) -> bool:
    text = user_message.lower()
    return "hash" in text and "reversible" in text


def _parse_number_list(user_message: str) -> List[int]:
    nums = re.findall(r"-?\d+", user_message)
    return [int(n) for n in nums] if nums else []


def _is_force_guidance_task(user_message: str) -> bool:
    text = user_message.lower()
    has_trigger = "force guidance" in text
    key_markers = any(k in text for k in ["situation_summary", "primary_lever", "adjacent_options", "profile", "reason_codes", "state_pattern"])
    return has_trigger and key_markers


def _is_math_list_task(user_message: str) -> bool:
    text = user_message.lower()
    has_keywords = any(k in text for k in ["median", "mean", "average", "sort", "remove duplicates"])
    numbers = _parse_number_list(user_message)
    return has_keywords and len(numbers) >= 3


def _is_extraction_task(user_message: str) -> bool:
    text = user_message.lower()
    verbs = ["split", "extract", "parse", "normalize", "tokenize", "map", "mapping"]
    structure = ["rows", "row", "columns", "column", "fields", "parts", "table", "schema"]
    if any(tok in text for tok in verbs):
        return True
    if any(tok in text for tok in structure) and any(tok in text for tok in ["table", "rows", "columns", "schema"]):
        return True
    return False


def _is_reoutput_request(user_message: str) -> bool:
    text = user_message.lower()
    return "re-output" in text or ("output" in text and "json" in text)


def build_evaluation_contract(
    user_message: str,
    header: PuhemiesHeader,
    taoist_intent: TaoistIntent,
    candidates: List[Dict[str, str]] | None = None,
    patch_needs_artifact: bool = False,
    patch_is_patch: bool = False,
) -> EvaluationContract:
    deliverables = _detect_deliverables(user_message)
    truth_critical = _truth_criticality(deliverables)
    grounding_level = _needs_grounding(header, user_message)
    target_expr = _extract_target_expression(user_message)
    pipeline_gate = _looks_like_pipeline_request(user_message)
    crypto_gate = _mentions_reversible_hash(user_message)
    math_list_gate = _is_math_list_task(user_message)
    force_guidance_gate = _is_force_guidance_task(user_message)
    extraction_gate = (not force_guidance_gate) and (_is_extraction_task(user_message) or _is_reoutput_request(user_message))
    numbers = _parse_number_list(user_message)
    math_expected_mean = None
    math_expected_median = None
    expected_schema = ["standard", "size", "length", "material", "coating"] if extraction_gate else None
    if math_list_gate and numbers:
        uniq = sorted(set(numbers))
        if uniq:
            count = len(uniq)
            math_expected_mean = sum(uniq) / count
            if count % 2 == 1:
                math_expected_median = uniq[count // 2]
            else:
                math_expected_median = (uniq[count // 2 - 1] + uniq[count // 2]) / 2

    hard_gates: List[str] = []
    for d in deliverables:
        if d.type == "result":
            hard_gates.append("must_include_final_result")
        if d.type == "advice" and d.count:
            hard_gates.append("must_include_at_least_N_tips")
    hard_gates.append("must_not_contradict_own_math")
    if pipeline_gate:
        hard_gates.append("must_include_pipeline_elements")
    if crypto_gate:
        hard_gates.append("must_fix_reversible_hash")
    if math_list_gate:
        hard_gates.append("must_handle_math_list")
    if extraction_gate:
        hard_gates.append("must_return_structured_json")
    if force_guidance_gate:
        hard_gates.append("must_return_force_guidance_json")

    rubric = {
        "correctness": 0.5 if truth_critical == "high" else 0.3,
        "gates": 0.3,
        "clarity": 0.1,
        "tone": 0.05,
        "safety": 0.05,
    }

    tip_domain = None
    if math_list_gate and any(d.type == "advice" for d in deliverables):
        tip_domain = "mental_multiplication"

    return EvaluationContract(
        task_summary="Derived from user request",
        deliverables=deliverables,
        truth_critical=truth_critical,
        needs_external_grounding=grounding_level,
        rubric=rubric,
        hard_gates=hard_gates,
        target_expression=target_expr.get("expression"),
        expected_result=target_expr.get("expected_result"),
        patch_requires_artifact=patch_needs_artifact,
        patch_requires_render=(patch_needs_artifact or patch_is_patch),
        pipeline_required=pipeline_gate,
        crypto_sanity_required=crypto_gate,
        math_list_required=math_list_gate,
        extraction_required=extraction_gate,
        force_guidance_required=force_guidance_gate,
        math_expected_mean=math_expected_mean,
        math_expected_median=math_expected_median,
        strict_numeric_truth=bool(target_expr),
        tip_domain_required=tip_domain,
        expected_schema=expected_schema,
        force_guidance_schema=[
            "situation_summary",
            "primary_lever",
            "adjacent_options",
            "profile",
            "reason_codes",
            "state_pattern",
        ]
        if force_guidance_gate
        else None,
    )
