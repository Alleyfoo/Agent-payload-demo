from app.circuits.force_guidance import ForceGuidanceCircuit


def test_force_guidance_is_deterministic():
    circuit = ForceGuidanceCircuit()
    text = "Olen jumissa ja en jaksa enää, suunta epäselvä."

    first = circuit.run("run-1", text).guidance
    second = circuit.run("run-2", text).guidance

    assert first.reason_codes == second.reason_codes
    assert first.profile.as_dict() == second.profile.as_dict()
    assert first.primary_lever.name == second.primary_lever.name


def test_uncertainty_drives_question_focus():
    circuit = ForceGuidanceCircuit()
    guidance = circuit.run("run-3", "En tiedä mitä pitäisi tehdä, kaikki on epäselvää.").guidance

    assert "kynnyskysymys" in guidance.primary_lever.first_step.lower() or "question" in guidance.primary_lever.name.lower()
    assert "high_uncertainty" in guidance.reason_codes


def test_inertia_triggers_small_movement_lever():
    circuit = ForceGuidanceCircuit()
    guidance = circuit.run("run-4", "Olen jumissa ja mikään ei liiku, en jaksa enää.").guidance

    assert "askel" in guidance.primary_lever.first_step.lower() or "kitka" in guidance.primary_lever.first_step.lower()
    assert "high_inertia" in guidance.reason_codes
