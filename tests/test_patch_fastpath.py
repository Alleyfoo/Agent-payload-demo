import copy

from app.agents.shadow import ShadowAgent
from app.speaker import SpeakerAgent


class DummyLLM:
    def generate(self, *_args, **_kwargs):
        raise RuntimeError("LLM should not be called in fast-path")


def test_patch_fast_path_updates_artifact_and_sets_flags():
    llm = DummyLLM()
    shadow = ShadowAgent()
    speaker = SpeakerAgent(llm, shadow)

    initial_artifact = [{"standard": "DIN 931", "size": "M6", "length": 20, "material": "a2", "coating": "zp"}]
    speaker._set_artifact_state(copy.deepcopy(initial_artifact), artifact_type="extraction_result", schema={"standard": "s", "size": "s", "length": "n", "material": "s", "coating": "s"})

    msg = "Set coating to zinc plated in that table"
    result = speaker.process_hierarchical(msg, task_type="data_extraction")

    assert result["verdict"] == "patch_applied"
    assert result.get("patch_applied") is True
    assert "zinc" in result["healing_response"].lower()
    # schema preserved: no extra keys
    state = speaker._get_artifact_state()
    assert isinstance(state.active_artifact, list)
    assert set(state.active_artifact[0].keys()) == set(initial_artifact[0].keys())
