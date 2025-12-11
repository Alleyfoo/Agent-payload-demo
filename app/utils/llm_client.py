from __future__ import annotations

import json
import os
from typing import Optional

import requests


class LLMClient:
    """Wrapper around Ollama HTTP API with optional mock responses."""

    def __init__(
        self,
        model: str = "llama3.1",
        base_url: str = "http://localhost:11434",
        use_mock: Optional[bool] = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        env_mock = os.getenv("OLLAMA_USE_MOCK")
        self.use_mock = use_mock if use_mock is not None else env_mock == "1"

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        if self.use_mock:
            return self._mock_response(prompt)

        payload = {"model": self.model, "prompt": prompt}
        if system:
            payload["system"] = system

        response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        # Ollama returns streaming results; consolidate if needed
        if "response" in data:
            return data["response"].strip()
        return json.dumps(data)

    def _mock_response(self, prompt: str) -> str:
        """Lightweight mock that fabricates deterministic output for tests."""
        if "lesson_v1" in prompt:
            return (
                "# Title: Example lesson\n\n"
                "## Concept\nList comprehension allows compact list creation.\n\n"
                "## Code Example\n````python\n[square for square in range(5)]\n````\n\n"
                "## Exercise\nCreate squares of even numbers up to 10."
            )
        if "task_type" in prompt and "topic" in prompt:
            return json.dumps(
                {
                    "task_type": "lesson_page",
                    "topic": "python_lists",
                    "language": "fi",
                    "target_level": "beginner",
                    "constraints": ["markdown output"],
                    "status": "ok",
                }
            )
        return "Generated content."
