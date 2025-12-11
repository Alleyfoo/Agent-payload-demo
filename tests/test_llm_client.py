import json
from unittest import TestCase, mock

from app.utils.llm_client import LLMClient


class FakeResponse:
    def __init__(self, lines):
        self.status_code = 200
        self._lines = lines
        self.content = b"".join(lines)

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            if decode_unicode:
                yield line.decode("utf-8")
            else:
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

    def test_streaming_handles_utf8_chunks(self):
        emoji = " \U0001f600"
        streamed = [
            b'{"response":"Hello", "done": false}\n',
            b'{"response":" world", "done": false}\n',
            b'{"response":"' + emoji.encode("utf-8") + b'", "done": false}\n',
            b'{"done": true}\n',
        ]

        with mock.patch("requests.post", return_value=FakeResponse(streamed)):
            client = LLMClient(use_mock=False)
            result = client.generate("hi")

        self.assertEqual(result, f"Hello world{emoji}")

    def test_streaming_reconstructs_canned_payload(self):
        streamed = [
            b'{"model":"llama3.1","response":"Hello ","done": false}\n',
            b'{"model":"llama3.1","response":"world","done": false}\n',
            b'{"model":"llama3.1","response":"!","done": false}\n',
            b'{"model":"llama3.1","done": true}\n',
        ]

        with mock.patch("requests.post", return_value=FakeResponse(streamed)):
            client = LLMClient(use_mock=False)
            result = client.generate("hi")

        self.assertEqual(result, "Hello world!")
