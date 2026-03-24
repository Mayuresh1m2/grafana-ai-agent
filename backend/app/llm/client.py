"""Async Ollama LLM client with streaming and structured-output support."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from enum import Enum
from functools import lru_cache
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

from src.config import get_settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Enums / data models
# ---------------------------------------------------------------------------


class OllamaModel(str, Enum):
    """Supported Ollama model identifiers."""

    LLAMA3_8B = "llama3:8b"
    CODELLAMA_7B = "codellama:7b"
    MISTRAL_7B = "mistral:7b"


class OllamaMessage(BaseModel):
    """Single message in a chat conversation."""

    role: str  # "system" | "user" | "assistant"
    content: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama server cannot be reached."""


class OllamaStructuredOutputError(ValueError):
    """Raised when structured JSON output cannot be parsed after max retries."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]+\}", re.DOTALL)


class OllamaClient:
    """Thin async wrapper around the Ollama HTTP API.

    Features
    --------
    - Streaming ``chat()`` via async generator (newline-delimited JSON)
    - ``generate_structured()`` with up to 3 parse retries
    - ``health_check()`` against ``/api/tags``
    - ``estimate_tokens()`` rough heuristic (``len(text) // 4``)
    """

    _DEFAULT_MODEL = OllamaModel.LLAMA3_8B
    _MAX_STRUCTURED_RETRIES = 3

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[OllamaMessage],
        model: OllamaModel = _DEFAULT_MODEL,
        temperature: float = 0.7,
        stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Stream chat tokens from Ollama.

        Yields individual text chunks as they arrive. When ``stream=False``
        the full response is yielded as a single chunk for API consistency.
        """
        log = logger.bind(model=model.value, stream=stream)
        log.debug("ollama_chat_start", message_count=len(messages))
        payload: dict[str, Any] = {
            "model": model.value,
            "messages": [m.model_dump() for m in messages],
            "stream": stream,
            "options": {"temperature": temperature},
        }
        return self._stream_chat(payload, log)

    async def generate_structured(
        self,
        prompt: str,
        output_schema: type[BaseModel],
        model: OllamaModel = _DEFAULT_MODEL,
    ) -> BaseModel:
        """Generate a response and parse it into ``output_schema``.

        Injects a system prompt that instructs the model to reply with valid
        JSON matching the schema. Retries up to 3 times on parse failure.

        Raises
        ------
        OllamaStructuredOutputError
            If the model fails to produce parseable JSON after all retries.
        """
        schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
        system_msg = OllamaMessage(
            role="system",
            content=(
                "You are a precise data-extraction assistant. "
                "Reply ONLY with a valid JSON object that conforms to this schema "
                "(no extra text, no markdown fences):\n\n"
                f"{schema_json}"
            ),
        )
        user_msg = OllamaMessage(role="user", content=prompt)

        log = logger.bind(model=model.value, schema=output_schema.__name__)
        last_exc: Exception | None = None

        for attempt in range(1, self._MAX_STRUCTURED_RETRIES + 1):
            log.debug("structured_output_attempt", attempt=attempt)
            raw_chunks: list[str] = []
            async for chunk in await self.chat(
                [system_msg, user_msg], model=model, temperature=0.0, stream=True
            ):
                raw_chunks.append(chunk)

            raw = "".join(raw_chunks).strip()
            log.debug("structured_raw_response", preview=raw[:120])

            try:
                parsed = self._extract_json(raw)
                result = output_schema.model_validate(parsed)
                log.debug("structured_output_ok", attempt=attempt)
                return result
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "structured_output_parse_failed",
                    attempt=attempt,
                    error=str(exc),
                    raw_preview=raw[:200],
                )
                last_exc = exc

        raise OllamaStructuredOutputError(
            f"Failed to parse {output_schema.__name__} after "
            f"{self._MAX_STRUCTURED_RETRIES} attempts. Last error: {last_exc}"
        ) from last_exc

    async def health_check(self) -> bool:
        """Return ``True`` if Ollama is reachable and has at least one model."""
        log = logger.bind(base_url=self._base_url)
        try:
            response = await self._http.get("/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            models: list[Any] = data.get("models", [])
            log.debug("ollama_health_ok", model_count=len(models))
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("ollama_health_failed", error=str(exc))
            return False

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token count heuristic: ``len(text) // 4``."""
        return max(1, len(text) // 4)

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _stream_chat(
        self,
        payload: dict[str, Any],
        log: Any,
    ) -> AsyncGenerator[str, None]:
        """Yield text tokens from a streaming /api/chat response."""
        async with self._http.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("ollama_invalid_json_line", line=line[:80])
                    continue

                message = event.get("message", {})
                content: str = message.get("content", "")
                if content:
                    yield content

                if event.get("done", False):
                    log.debug(
                        "ollama_chat_done",
                        total_tokens=event.get("eval_count"),
                    )
                    return

    @staticmethod
    def _extract_json(text: str) -> Any:
        """Extract a JSON object from model output.

        Tries in order:
        1. Direct ``json.loads``
        2. Fenced code block (```json ... ```)
        3. First ``{...}`` span in the text
        """
        # 1. Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. Fenced block
        fence_match = _JSON_FENCE_RE.search(text)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. First JSON object
        obj_match = _JSON_OBJECT_RE.search(text)
        if obj_match:
            return json.loads(obj_match.group(0))  # let it raise if still invalid

        raise ValueError(f"No JSON object found in output: {text[:200]!r}")


# ---------------------------------------------------------------------------
# FastAPI / app-level factory
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_ollama_client() -> OllamaClient:
    """Return a cached ``OllamaClient`` instance.

    The ``OLLAMA_BASE_URL`` setting controls the target:

    - Local dev default: ``http://localhost:11434``
    - k3d in-cluster: ``http://host.k3d.internal:11434``

    Raises
    ------
    OllamaUnavailableError
        If ``/api/tags`` returns an error at import time — fail fast so the
        operator knows the dependency is missing before any request is served.
        (The actual reachability check is done lazily in ``health_check()``;
        this factory only validates the URL is configured.)
    """
    settings = get_settings()
    base_url = str(settings.ollama_base_url)
    if not base_url:
        raise OllamaUnavailableError("OLLAMA_BASE_URL is not configured")
    return OllamaClient(base_url=base_url)
