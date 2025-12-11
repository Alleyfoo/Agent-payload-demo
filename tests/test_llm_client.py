import json
from unittest import TestCase, mock

from app.utils.llm_client import LLMClient


class FakeResponse:
    def __init__(self, lines):
        self.status_code = 200
        self._lines = lines
        self.content = b"".join(lines)

    def iter_lines(self):
        for line in self._lines:
            yield line

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError("HTTP error")

    @property
    def text(self):
        return self.content.decode("utf-8")

    def json(self):
        return json.loads(self.text)


class TestLLMClient(TestCase):
    def test_streaming_chunks_concatenated(self):
        streamed = [
            b'{"response":"Hello", "done": false}',
            b'{"response":" world", "done": false}',
            b'{"done": true}',
        ]

        with mock.patch("requests.post", return_value=FakeResponse(streamed)) as mocked:
            client = LLMClient(use_mock=False)
            result = client.generate("hi")

        mocked.assert_called_once()
        self.assertEqual(result, "Hello world")

    def test_streaming_ignores_decode_errors(self):
        streamed = [
            b'{"response":"Hello"}\x80',
            b'{"response":" world"}\n',
            b'{"done": true}\n',
        ]

        with mock.patch("requests.post", return_value=FakeResponse(streamed)):
            client = LLMClient(use_mock=False)
            result = client.generate("hi")

        self.assertEqual(result, "Hello world")
