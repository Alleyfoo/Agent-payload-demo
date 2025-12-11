import unittest

from app.circuits.method import MethodProducerCircuit
from app.models import TaskSpec
from app.utils.llm_client import LLMClient


class DummyLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, prompt: str) -> str:  # pragma: no cover - trivial passthrough
        return self.response


class ExtractSectionsTest(unittest.TestCase):
    def setUp(self) -> None:
        response = (
            "# Title: Lesson intro\n"
            "A short summary line.\n"
            "## Concept – overview\n"
            "Concept body goes here.\n"
            "## Code Example\n"
            "print('hi')\n"
            "## Exercise\n"
            "Do the thing."
        )
        self.circuit = MethodProducerCircuit(DummyLLM(response))

    def test_extract_sections_handles_punctuation_after_heading(self) -> None:
        sections = ["title", "concept", "code_example", "exercise"]
        extracted = self.circuit._extract_sections(self.circuit.llm.response, sections)

        self.assertIn("title", extracted)
        self.assertIn("concept", extracted)
        self.assertEqual(extracted["title"], "Lesson intro\nA short summary line.")
        self.assertIn("Concept body goes here.", extracted["concept"])

    def test_run_returns_sections_from_marked_headings(self) -> None:
        task_spec = TaskSpec(
            run_id="run-1",
            task_type="lesson_page",
            topic="testing",
            language="en",
            target_level="beginner",
            constraints=[],
            status="ok",
        )

        result = self.circuit.run("run-1", task_spec)

        sections_content = result["sections_content"]
        self.assertIn("title", sections_content)
        self.assertIn("concept", sections_content)
        self.assertEqual(result["content_package"].warnings, [])
        self.assertTrue(result["content_package"].method_respected)

    def test_extract_sections_handles_trailing_punctuation_only(self) -> None:
        response = (
            "# Title!\n"
            "Summary line here.\n"
            "## Concept?\n"
            "Explanation details."
        )
        circuit = MethodProducerCircuit(DummyLLM(response))
        sections = ["title", "concept", "code_example", "exercise"]

        extracted = circuit._extract_sections(response, sections)

        self.assertIn("title", extracted)
        self.assertIn("concept", extracted)
        self.assertNotIn("code_example", extracted)
        self.assertNotIn("exercise", extracted)

    def test_extract_sections_uses_llm_mock_output(self) -> None:
        llm = LLMClient(use_mock=True)
        circuit = MethodProducerCircuit(llm)
        response = llm.generate("lesson_v1")

        sections = ["title", "concept", "code_example", "exercise"]
        extracted = circuit._extract_sections(response, sections)

        self.assertEqual(set(sections), set(extracted.keys()))
        self.assertIn("Example lesson", extracted["title"])
        self.assertIn("List comprehension", extracted["concept"])

    def test_run_with_mock_llm_covers_all_sections(self) -> None:
        circuit = MethodProducerCircuit(LLMClient(use_mock=True))
        task_spec = TaskSpec(
            run_id="run-mock",
            task_type="lesson_page",
            topic="list comprehensions",
            language="en",
            target_level="beginner",
            constraints=["markdown output"],
            status="ok",
        )

        result = circuit.run("run-mock", task_spec)

        sections_content = result["sections_content"]
        self.assertEqual(result["content_package"].warnings, [])
        self.assertTrue(result["content_package"].method_respected)
        self.assertIn("title", sections_content)
        self.assertIn("concept", sections_content)
        self.assertIn("code_example", sections_content)
        self.assertIn("exercise", sections_content)

    def test_run_mock_output_with_heading_descriptors_has_no_missing_warnings(self) -> None:
        circuit = MethodProducerCircuit(LLMClient(use_mock=True))
        task_spec = TaskSpec(
            run_id="run-heading",
            task_type="lesson_page",
            topic="mock headings",
            language="en",
            target_level="beginner",
            constraints=["markdown output"],
            status="ok",
        )

        result = circuit.run("run-heading", task_spec)

        self.assertEqual(result["content_package"].warnings, [])
        self.assertEqual(
            set(result["sections_content"].keys()),
            {"title", "concept", "code_example", "exercise"},
        )


if __name__ == "__main__":
    unittest.main()
