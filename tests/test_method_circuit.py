import unittest

from app.circuits.method import MethodProducerCircuit
from app.models import TaskSpec


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
        self.assertEqual(extracted["title"], "A short summary line.")
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


if __name__ == "__main__":
    unittest.main()
