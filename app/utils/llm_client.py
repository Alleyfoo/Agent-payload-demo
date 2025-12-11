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

        payload = {"model": self.model, "prompt": prompt, "stream": True}
        if system:
            payload["system"] = system

        stream = bool(payload.get("stream", False))
        response = requests.post(
            f"{self.base_url}/api/generate", json=payload, timeout=60, stream=stream
        )
        response.raise_for_status()

        if stream:
            chunks: list[str] = []
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                if isinstance(line, bytes):
                    try:
                        decoded_line = line.decode("utf-8")
                    except UnicodeDecodeError:
                        decoded_line = line.decode("utf-8", errors="replace")
                else:
                    decoded_line = line

                try:
                    event = json.loads(decoded_line)
                except json.JSONDecodeError:
                    continue

                fragment = event.get("response")
                if isinstance(fragment, str):
                    chunks.append(fragment)
                if event.get("done"):
                    break

            if chunks:
                return "".join(chunks).strip()

        try:
            data = response.json()
            if isinstance(data, dict) and "response" in data:
                return data["response"].strip()
            return json.dumps(data)
        except (json.JSONDecodeError, ValueError):
            return response.content.decode("utf-8", errors="replace")

    def _mock_response(self, prompt: str) -> str:
        """Lightweight mock that fabricates deterministic output for tests."""
        if "lesson_v1" in prompt:
            return (
                "# Title: Example lesson\n\n"
                "## Concept – overview\nList comprehension allows compact list creation.\n\n"
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
