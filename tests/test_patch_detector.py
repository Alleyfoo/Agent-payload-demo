from app.patch_detector import PatchDetector


def test_apply_job_not_patch():
    detector = PatchDetector()
    info = detector.detect("I want to apply for a job in Helsinki.")
    assert info.get("is_patch") is False


def test_table_anchor_triggers_patch():
    detector = PatchDetector()
    info = detector.detect("Set coating to zinc plated in that table, keep other fields.")
    assert info.get("is_patch") is True
    assert info.get("needs_artifact") is True
