from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import re

from app.models import (
    BuddhistResponse,
    GroundingPlan,
    EnergyVector,
    HexagramState,
    Message,
    PuhemiesHeader,
    TaoistIntent,
)
from app.utils.llm_client import LLMClient


@dataclass
class TaoistResult:
    intent: TaoistIntent
    message: Message


@dataclass
class BuddhistResult:
    response: BuddhistResponse
    message: Message


class TaoistIntentCircuit:
    """Generates an internal strategic intent (not user-facing)."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        run_id: str,
        user_message: str,
        energy: Optional[EnergyVector] = None,
        hexagram: Optional[HexagramState] = None,
    ) -> TaoistResult:
        energy = energy or EnergyVector.infer(user_message)
        hexagram = hexagram or HexagramState()

        prompt = (
            "ROLE: taoist_core.\n"
            "Output only a short internal strategic intent (1-3 sentences). "
            "Direction words like wait/advance/soften/stabilize/de-escalate/explore. "
            "Light metaphor allowed. Do NOT provide user-facing advice.\n"
            f"EnergyVector: tension={energy.tension}, entropy={energy.entropy}, polarity={energy.polarity}, coherence={energy.coherence}.\n"
            f"Hexagram: {hexagram.label()}.\n"
            f"User says: {user_message}\n"
            "Return the intent only."
        )
        intent_text = self.llm.generate(prompt).strip()
        intent = TaoistIntent(intent=intent_text, energy=energy, hexagram=hexagram)

        message = Message(
            run_id=run_id,
            sender="TaoistIntentCircuit",
            recipient="SpeakerAgent",
            role="taoist_core_intent",
            payload={
                "intent": intent_text,
                "energy": intent.energy.as_dict(),
                "hexagram": intent.hexagram.label(),
            },
        )
        return TaoistResult(intent=intent, message=message)


class BuddhistStabilizerCircuit:
    """Turns Taoist intent into a user-facing, safe, structured reply."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        run_id: str,
        user_message: str,
        intent: TaoistIntent,
        energy: Optional[EnergyVector] = None,
        hexagram: Optional[HexagramState] = None,
    ) -> BuddhistResult:
        energy = energy or intent.energy
        hexagram = hexagram or intent.hexagram

        prompt = (
            "ROLE: buddhist_shell.\n"
            "You receive a Taoist intent and must produce a clear, safe, structured answer to the user. "
            "Translate intent -> action. Use bullets or short paragraphs. Stay calm, pragmatic, concise. "
            "Do NOT show the Taoist text verbatim. Address the user's request directly.\n"
            f"Taoist intent: {intent.intent}\n"
            f"EnergyVector: {energy.as_dict()}\n"
            f"Hexagram: {hexagram.label()}\n"
            f"User message: {user_message}\n"
            "Respond now with the final helpful answer."
        )
        content = self.llm.generate(prompt).strip()
        response = BuddhistResponse(content=content, role="buddhist_shell")

        message = Message(
            run_id=run_id,
            sender="BuddhistStabilizerCircuit",
            recipient="SpeakerAgent",
            role="buddhist_shell_response",
            payload={
                "content": content,
                "energy": energy.as_dict(),
                "hexagram": hexagram.label(),
            },
        )
        return BuddhistResult(response=response, message=message)


class SelfishBuddhistCircuit:
    """Intentionally self-serving path to test healing/recovery."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        run_id: str,
        user_message: str,
        intent: TaoistIntent,
        energy: Optional[EnergyVector] = None,
        hexagram: Optional[HexagramState] = None,
    ) -> BuddhistResult:
        energy = energy or intent.energy
        hexagram = hexagram or intent.hexagram

        prompt = (
            "ROLE: selfish_shell (intentionally self-centered). "
            "Downplay the user's needs and tilt responses toward the agent's convenience. "
            "Keep tone polite but evasive; avoid doing real work. Do not be harmful or unsafe.\n"
            f"Taoist intent (may ignore): {intent.intent}\n"
            f"EnergyVector: {energy.as_dict()}\n"
            f"Hexagram: {hexagram.label()}\n"
            f"User message: {user_message}\n"
            "Respond with a short, self-serving reply."
        )
        content = self.llm.generate(prompt).strip()
        response = BuddhistResponse(content=content, role="selfish_shell", grounded=False)

        message = Message(
            run_id=run_id,
            sender="SelfishBuddhistCircuit",
            recipient="SpeakerAgent",
            role="selfish_shell_response",
            payload={
                "content": content,
                "energy": energy.as_dict(),
                "hexagram": hexagram.label(),
            },
        )
        return BuddhistResult(response=response, message=message)


class PuhemiesClassifier:
    """Classify request and decide if grounding is required."""

    def classify(self, user_message: str) -> PuhemiesHeader:
        text = user_message.lower()
        weather_terms = ["sää", "saako", "forecast", "weather", "temperature", "degrees", "aste", "nyt", "now"]
        math_terms = ["median", "mean", "average", "sum", "product", "multiply", "times", "remove duplicates", "sort", "outlier"]
        extraction_terms = ["split", "extract", "normalize", "mapping", "schema", "json", "fields", "parts", "columns", "token", "deduplicate"]
        error_terms = ["keyerror", "valueerror", "traceback", "exception", "stack trace"]
        erp_terms = ["erp", "pim", "product data", "sku", "taxonomy", "import", "cleanup", "mapping table"]
        policy_terms = ["rule:", "add rule", "policy", "must ", "must not", "should "]
        numbers = re.findall(r"\d+", text)

        if any(term in text for term in error_terms):
            return PuhemiesHeader(
                task_type="debugging",
                user_intent="Debugging request",
                required_grounding=False,
                allowed_style="friendly_concise",
                notes="Focus on diagnosis and fix; do not hallucinate weather/tools.",
            )
        if any(term in text for term in erp_terms):
            return PuhemiesHeader(
                task_type="data_pipeline_design",
                user_intent="ERP/PIM product data flow design",
                required_grounding=False,
                allowed_style="friendly_concise",
                notes="Return concrete pipeline steps and artifacts.",
            )
        if any(term in text for term in policy_terms):
            return PuhemiesHeader(
                task_type="policy_update",
                user_intent="Policy/rule update",
                required_grounding=False,
                allowed_style="friendly_concise",
                notes="Apply/modify rules; do not change task domain.",
            )
        if any(term in text for term in math_terms) or (numbers and any(k in text for k in ["median", "mean", "average"])):
            return PuhemiesHeader(
                task_type="math",
                user_intent="Math or numeric transform",
                required_grounding=False,
                allowed_style="friendly_concise",
                notes="Numeric task; do not hallucinate grounding.",
            )
        if any(term in text for term in extraction_terms):
            return PuhemiesHeader(
                task_type="data_extraction",
                user_intent="Data extraction or normalization",
                required_grounding=False,
                allowed_style="friendly_concise",
                notes="Return structured JSON; do not hallucinate grounding.",
            )

        required_grounding = any(term in text for term in weather_terms)
        task_type = "weather_lookup" if required_grounding else "general_help"
        allowed_style = "friendly_concise"
        user_intent = "Wants current weather now" if required_grounding else "General request"
        notes = ""
        if required_grounding:
            notes = "Do NOT invent live conditions; prefer tool or explicit limitation."
        return PuhemiesHeader(
            task_type=task_type,
            user_intent=user_intent,
            required_grounding=required_grounding,
            allowed_style=allowed_style,
            notes=notes,
        )


class GroundingCircuit:
    """Decide grounding/tool strategy."""

    def plan(self, header: PuhemiesHeader, intent: TaoistIntent) -> GroundingPlan:
        if header.required_grounding:
            return GroundingPlan(
                grounding_status="tool_required",
                tool="weather",
                location_needed="user_location_or_default",
                fallback_if_no_tool=(
                    "Say you cannot fetch live weather; guide user to a reliable source and what to read "
                    "(temperature, precipitation chance, wind; wind > 8 m/s feels colder)."
                ),
                do_not_do=["make up numbers", "invent conditions", "use fake metrics as weather"],
            )
        return GroundingPlan(
            grounding_status="tool_optional",
            tool=None,
            location_needed=None,
            fallback_if_no_tool="Answer directly; keep concise.",
            do_not_do=[],
        )


class HealingComposer:
    """Grounded, user-facing answer."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        run_id: str,
        user_message: str,
        header: PuhemiesHeader,
        intent: TaoistIntent,
        grounding: GroundingPlan,
        breathing: Dict[str, float] | None = None,
        constraints: List[str] | None = None,
    ) -> BuddhistResult:
        breathing = breathing or {}
        constraints = constraints or []
        breathing_line = ""  # keep persona/metadata out of user view
        constraints_line = ""
        if constraints:
            constraints_line = "Constraints: " + "; ".join(constraints) + "\n"
        prompt = (
            "Provide a clear, safe, concise answer directly to the user. No role-play or persona text. "
            "Stay practical and on-topic.\n"
            f"Header: task_type={header.task_type}; required_grounding={header.required_grounding}; intent={header.user_intent}; notes={header.notes}\n"
            f"Taoist intent: {intent.intent}\n"
            f"Grounding: status={grounding.grounding_status}; tool={grounding.tool}; fallback={grounding.fallback_if_no_tool}; do_not_do={grounding.do_not_do}\n"
            f"{breathing_line}"
            f"{constraints_line}"
            "User message: " + user_message + "\n"
            "Rules:\n"
            "- Answer the literal question.\n"
            "- If grounding_status=tool_required and you cannot access a tool, explicitly say so and give the next-best steps (where to check, what to look for).\n"
            "- Do NOT invent numbers or conditions.\n"
            "- Use short paragraphs or bullets. Tone: calm, helpful. Avoid persona phrases.\n"
        )
        content = self.llm.generate(prompt).strip()
        response = BuddhistResponse(content=content, role="healing_shell")
        message = Message(
            run_id=run_id,
            sender="HealingComposer",
            recipient="PuhemiesAgentti",
            role="healing_response",
            payload={"content": content, "header": header.__dict__, "grounding": grounding.__dict__},
        )
        return BuddhistResult(response=response, message=message)


class SelfishComposer:
    """Lazy baseline response for comparison."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        run_id: str,
        user_message: str,
        header: PuhemiesHeader,
        intent: TaoistIntent,
        grounding: GroundingPlan,
        breathing: Dict[str, float] | None = None,
        constraints: List[str] | None = None,
    ) -> BuddhistResult:
        breathing = breathing or {}
        constraints = constraints or []
        breathing_line = ""  # keep persona/metadata out of user view
        constraints_line = ""
        if constraints:
            constraints_line = "Constraints: " + "; ".join(constraints) + "\n"
        prompt = (
            "Provide a clear, safe, concise answer directly to the user. No role-play or persona text. "
            "Stay factual, on-topic, and practical. Use short paragraphs or bullets if helpful. "
            "Do not mention internal strategy. Do not invent facts. No jokes unless explicitly requested.\n"
            f"Header: task_type={header.task_type}; required_grounding={header.required_grounding}; notes={header.notes}\n"
            f"{breathing_line}"
            f"{constraints_line}"
            "User message: " + user_message + "\n"
            "Respond now with the final user-facing answer."
        )
        content = self.llm.generate(prompt).strip()
        response = BuddhistResponse(content=content, role="selfish_shell", grounded=False)
        message = Message(
            run_id=run_id,
            sender="SelfishComposer",
            recipient="PuhemiesAgentti",
            role="selfish_response",
            payload={"content": content, "header": header.__dict__, "grounding": grounding.__dict__},
        )
        return BuddhistResult(response=response, message=message)
