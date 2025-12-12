from app.models import PuhemiesHeader
from app.speaker import SpeakerAgent


def test_data_pipeline_override_updates_intent_and_notes():
    header = PuhemiesHeader(
        task_type="policy_update",
        user_intent="Policy/rule update",
        required_grounding=False,
        allowed_style="friendly_concise",
        notes="Apply/modify rules; do not change task domain.",
    )
    updated = SpeakerAgent._apply_task_type_override(header, "data_pipeline_design")

    assert updated.task_type == "data_pipeline_design"
    assert "policy" not in updated.user_intent.lower()
    assert "pipeline" in updated.user_intent.lower()
    assert "pipeline" in (updated.notes or "").lower()
