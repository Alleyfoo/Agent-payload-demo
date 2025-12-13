from __future__ import annotations

from pathlib import Path

from app.agents.shadow import ShadowAgent
from app.speaker import SpeakerAgent
from app.utils.llm_client import LLMClient


def _build_speaker(tmp_path: Path) -> tuple[SpeakerAgent, ShadowAgent]:
    llm = LLMClient(use_mock=True)
    shadow = ShadowAgent(storage_path=tmp_path / "shadow_reports.jsonl")
    speaker = SpeakerAgent(llm, shadow)
    return speaker, shadow


def test_force_guidance_attached_to_prompt_and_report(tmp_path):
    speaker, shadow = _build_speaker(tmp_path)

    result = speaker.process_and_summarize("Tarvitsen apua, suunta on epäselvä ja jumi.")
    guidance = result["details"].get("force_guidance")

    assert guidance
    assert "primary_lever" in guidance
    report = shadow.history[-1]
    assert report.get("force_guidance")
    assert "primary_lever" in report["force_guidance"]


def test_patch_fast_path_keeps_responses(tmp_path):
    speaker, _ = _build_speaker(tmp_path)
    output = speaker.process_dual_paths("output json\nDIN 933 bolt", task_type="data_ops")

    assert "compassionate_response" in output
    assert output["compassionate_response"]
    assert "Ensisijainen" in output["compassionate_response"]
