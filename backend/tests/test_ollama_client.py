"""Unit tests for app.llm.client — OllamaClient."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.llm.client import (
    OllamaClient,
    OllamaMessage,
    OllamaModel,
    OllamaStructuredOutputError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stream_lines(*chunks: str, done_extra: dict | None = None) -> list[bytes]:
    """Build newline-delimited JSON lines as Ollama /api/chat would emit."""
    lines: list[bytes] = []
    for chunk in chunks:
        line = json.dumps({"message": {"role": "assistant", "content": chunk}, "done": False})
        lines.append(line.encode())
    done_event = {"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 42}
    if done_extra:
        done_event.update(done_extra)
    lines.append(json.dumps(done_event).encode())
    return lines


async def _async_iter_lines(lines: list[bytes]) -> AsyncIterator[str]:
    for line in lines:
        yield line.decode()


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------


class TestChat:
    @pytest.fixture()
    def client(self) -> OllamaClient:
        return OllamaClient(base_url="http://localhost:11434")

    async def test_chat_yields_chunks(self, client: OllamaClient) -> None:
        lines = _make_stream_lines("Hello", ", ", "world", "!")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=_async_iter_lines(lines))
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client._http, "stream", return_value=mock_response):
            gen = await client.chat(
                [OllamaMessage(role="user", content="Hi")],
                model=OllamaModel.LLAMA3_8B,
            )
            collected: list[str] = []
            async for token in gen:
                collected.append(token)

        assert collected == ["Hello", ", ", "world", "!"]

    async def test_chat_skips_empty_content(self, client: OllamaClient) -> None:
        lines = [
            json.dumps({"message": {"role": "assistant", "content": ""}, "done": False}).encode(),
            json.dumps({"message": {"role": "assistant", "content": "hi"}, "done": False}).encode(),
            json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}).encode(),
        ]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=_async_iter_lines(lines))
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client._http, "stream", return_value=mock_response):
            gen = await client.chat(
                [OllamaMessage(role="user", content="ping")],
            )
            tokens = [t async for t in gen]

        assert tokens == ["hi"]

    async def test_chat_stops_at_done_sentinel(self, client: OllamaClient) -> None:
        lines = [
            json.dumps({"message": {"role": "assistant", "content": "A"}, "done": False}).encode(),
            json.dumps({"message": {"role": "assistant", "content": "B"}, "done": True}).encode(),
            # This line should never be reached
            json.dumps({"message": {"role": "assistant", "content": "C"}, "done": False}).encode(),
        ]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=_async_iter_lines(lines))
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client._http, "stream", return_value=mock_response):
            gen = await client.chat([OllamaMessage(role="user", content="x")])
            tokens = [t async for t in gen]

        assert "C" not in tokens

    async def test_chat_ignores_malformed_json_lines(self, client: OllamaClient) -> None:
        async def _lines() -> AsyncIterator[str]:
            yield "not-json"
            yield json.dumps({"message": {"role": "assistant", "content": "ok"}, "done": True})

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = MagicMock(return_value=_lines())
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client._http, "stream", return_value=mock_response):
            gen = await client.chat([OllamaMessage(role="user", content="x")])
            tokens = [t async for t in gen]

        assert tokens == []


# ---------------------------------------------------------------------------
# generate_structured — retry logic
# ---------------------------------------------------------------------------


class _Schema(BaseModel):
    answer: str
    confidence: float


class TestGenerateStructured:
    @pytest.fixture()
    def client(self) -> OllamaClient:
        return OllamaClient(base_url="http://localhost:11434")

    def _mock_chat(self, client: OllamaClient, responses: list[str]) -> None:
        """Replace client.chat with an async generator yielding responses in order."""
        call_count = 0

        async def _mock(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1

            async def _gen() -> AsyncIterator[str]:
                yield resp

            return _gen()

        client.chat = _mock  # type: ignore[method-assign]

    async def test_structured_parses_on_first_attempt(self, client: OllamaClient) -> None:
        payload = json.dumps({"answer": "yes", "confidence": 0.9})
        self._mock_chat(client, [payload])

        result = await client.generate_structured("question", _Schema)

        assert isinstance(result, _Schema)
        assert result.answer == "yes"
        assert result.confidence == pytest.approx(0.9)

    async def test_structured_parses_fenced_json(self, client: OllamaClient) -> None:
        fenced = "```json\n{\"answer\": \"maybe\", \"confidence\": 0.5}\n```"
        self._mock_chat(client, [fenced])

        result = await client.generate_structured("q", _Schema)
        assert result.answer == "maybe"

    async def test_structured_retries_on_parse_failure(self, client: OllamaClient) -> None:
        bad = "not valid json at all"
        good = json.dumps({"answer": "retry worked", "confidence": 1.0})
        # First two calls fail, third succeeds
        self._mock_chat(client, [bad, bad, good])

        result = await client.generate_structured("q", _Schema)
        assert result.answer == "retry worked"

    async def test_structured_raises_after_max_retries(self, client: OllamaClient) -> None:
        self._mock_chat(client, ["garbage"] * 3)

        with pytest.raises(OllamaStructuredOutputError, match="_Schema"):
            await client.generate_structured("q", _Schema)

    async def test_structured_exactly_three_retries(self, client: OllamaClient) -> None:
        """Verify that exactly 3 attempts are made before giving up."""
        attempts: list[int] = []

        async def _counting_chat(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
            attempts.append(1)

            async def _gen() -> AsyncIterator[str]:
                yield "bad json"

            return _gen()

        client.chat = _counting_chat  # type: ignore[method-assign]

        with pytest.raises(OllamaStructuredOutputError):
            await client.generate_structured("q", _Schema)

        assert len(attempts) == 3


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.fixture()
    def client(self) -> OllamaClient:
        return OllamaClient(base_url="http://localhost:11434")

    async def test_health_check_returns_true_when_ok(self, client: OllamaClient) -> None:
        mock_get = AsyncMock(
            return_value=MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"models": [{"name": "llama3:8b"}]}),
            )
        )
        with patch.object(client._http, "get", mock_get):
            assert await client.health_check() is True

    async def test_health_check_returns_false_on_http_error(self, client: OllamaClient) -> None:
        mock_get = AsyncMock(side_effect=Exception("connection refused"))
        with patch.object(client._http, "get", mock_get):
            assert await client.health_check() is False


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_estimate_tokens_basic(self) -> None:
        assert OllamaClient.estimate_tokens("hello") == 1  # 5 // 4 → 1
        assert OllamaClient.estimate_tokens("a" * 40) == 10
        assert OllamaClient.estimate_tokens("") == 1  # min 1

    def test_estimate_tokens_proportional(self) -> None:
        short = OllamaClient.estimate_tokens("x" * 100)
        long = OllamaClient.estimate_tokens("x" * 400)
        assert long == 4 * short


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_direct_json(self) -> None:
        assert OllamaClient._extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self) -> None:
        text = "Here is your answer:\n```json\n{\"a\": 2}\n```\nDone."
        assert OllamaClient._extract_json(text) == {"a": 2}

    def test_embedded_json(self) -> None:
        text = 'Sure! {"a": 3} is what you need.'
        assert OllamaClient._extract_json(text) == {"a": 3}

    def test_raises_on_no_json(self) -> None:
        with pytest.raises((ValueError, Exception)):
            OllamaClient._extract_json("no json here at all")
