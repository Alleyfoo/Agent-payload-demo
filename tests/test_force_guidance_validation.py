import json

from app.agents.shadow import ShadowAgent
from app.checkup_layer import build_evaluation_contract
from app.circuits.force_guidance import ForceGuidanceCircuit
from app.models import EnergyVector, HexagramState, PuhemiesHeader, TaoistIntent
from app.speaker import SpeakerAgent
from app.utils.llm_client import LLMClient


def test_contract_flags_force_guidance():
    header = PuhemiesHeader(task_type="force_guidance", user_intent="", required_grounding=False, allowed_style="friendly_concise")
    intent = TaoistIntent(intent="", energy=EnergyVector(), hexagram=HexagramState(0, "neutral"))
    message = "Force guidance only\nsituation_summary\nprimary_lever\nadjacent_options\nprofile\nreason_codes\nstate_pattern"

    contract = build_evaluation_contract(message, header, intent)

    assert contract.force_guidance_required is True
    assert contract.extraction_required is False
    assert "must_return_force_guidance_json" in contract.hard_gates


def test_shadow_gate_accepts_valid_force_guidance(tmp_path):
    shadow = ShadowAgent(storage_path=tmp_path / "shadow_reports.jsonl")
    fg_json = ForceGuidanceCircuit().run("r1", "Test guidance").guidance.as_json()
    contract_dict = {
        "hard_gates": ["must_return_force_guidance_json"],
        "deliverables": [],
        "expected_result": None,
        "patch_requires_artifact": False,
        "patch_requires_render": False,
        "pipeline_required": False,
        "crypto_sanity_required": False,
        "math_list_required": False,
        "extraction_required": False,
        "force_guidance_required": True,
        "math_expected_mean": None,
        "math_expected_median": None,
        "strict_numeric_truth": False,
        "tip_domain_required": None,
        "expected_schema": None,
        "force_guidance_schema": [
            "situation_summary",
            "primary_lever",
            "adjacent_options",
            "profile",
            "reason_codes",
            "state_pattern",
        ],
    }

    result = shadow.compare_outputs(
        "r1",
        [{"label": "healing", "role": "healing_shell", "text": fg_json, "header": {"required_grounding": False}}],
        contract=contract_dict,
        prune=False,
    )

    assert result.get("gate_violations") == {}


def test_speaker_returns_json_for_force_guidance_only(tmp_path):
    llm = LLMClient(use_mock=True)
    shadow = ShadowAgent(storage_path=tmp_path / "shadow_reports.jsonl")
    speaker = SpeakerAgent(llm, shadow)
    msg = "Force guidance only\nsituation_summary\nprimary_lever\nadjacent_options\nprofile\nreason_codes\nstate_pattern"

    result = speaker.process_hierarchical(msg)

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert "adjacent_options" in parsed and isinstance(parsed["adjacent_options"], list) and len(parsed["adjacent_options"]) == 3
