"""Async HTTP client for the Ollama inference API."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from functools import lru_cache

import httpx
import structlog

from src.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT_BASE = (
    "You are a Grafana AI assistant. You help SREs and developers analyse "
    "metrics, logs, and traces from their observability stack (Grafana, Loki, "
    "Prometheus, Tempo). Be concise, factual, and actionable. When uncertain, "
    "say so rather than guessing."
)

_SUGGESTIONS_INSTRUCTION = (
    "\n\nAfter your answer, on its own line, append exactly this (valid JSON array, "
    "no trailing text):\n"
    'SUGGESTIONS: ["follow-up question 1?", "follow-up question 2?", "follow-up question 3?"]\n'
    "The questions should be 2-3 concise things an on-call engineer would naturally investigate next. "
    "Do not include any text after the SUGGESTIONS line."
)


def parse_suggestions(text: str) -> tuple[str, list[str]]:
    """Split LLM output into (clean_answer, suggestions_list).

    Looks for a trailing ``SUGGESTIONS: [...]`` line and extracts it.
    Returns the original text unchanged if the marker is absent or malformed.
    """
    match = re.search(r"\nSUGGESTIONS:\s*(\[.*?\])\s*$", text.rstrip(), re.DOTALL)
    if match:
        try:
            items = json.loads(match.group(1))
            if isinstance(items, list):
                clean = text[: match.start()].rstrip()
                return clean, [str(s) for s in items[:3]]
        except (json.JSONDecodeError, ValueError):
            pass
    return text, []


class OllamaService:
    """Wraps the Ollama /api/generate endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_timeout),
        )

    @property
    def default_model(self) -> str:
        return self._settings.ollama_model

    async def generate(
        self,
        prompt: str,
        context: dict[str, str] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> tuple[str, int | None]:
        """Send a prompt to Ollama and return (answer, tokens_used).

        Returns a tuple so callers can surface token counts to the response
        without coupling the endpoint to implementation details.
        """
        effective_model = model or self._settings.ollama_model
        system_prompt = self._build_system_prompt(context or {})

        log = logger.bind(model=effective_model, prompt_len=len(prompt))
        log.debug("ollama_generate_start")

        payload: dict[str, object] = {
            "model": effective_model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        response = await self._client.post("/api/generate", json=payload)
        response.raise_for_status()
        data: dict[str, object] = response.json()

        answer = str(data.get("response", ""))
        tokens_used: int | None = data.get("eval_count")  # type: ignore[assignment]
        log.debug("ollama_generate_done", tokens_used=tokens_used)
        return answer, tokens_used

    async def list_models(self) -> list[str]:
        """Return model names available in this Ollama instance."""
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        data: dict[str, object] = response.json()
        models: list[dict[str, object]] = data.get("models", [])  # type: ignore[assignment]
        return [str(m.get("name", "")) for m in models]

    async def generate_stream(
        self,
        prompt: str,
        system: str,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Stream an Ollama response token-by-token as an async generator."""
        effective_model = model or self._settings.ollama_model
        payload: dict[str, object] = {
            "model": effective_model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with self._client.stream("POST", "/api/generate", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    token: str = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

    async def aclose(self) -> None:
        await self._client.aclose()

    def _build_system_prompt(self, context: dict[str, str]) -> str:
        base = _SYSTEM_PROMPT_BASE
        if context:
            ctx_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            base = f"{base}\n\nContext provided by the user:\n{ctx_lines}"
        return base + _SUGGESTIONS_INSTRUCTION


@lru_cache(maxsize=1)
def get_ollama_service() -> OllamaService:
    """FastAPI dependency — returns a cached OllamaService singleton."""
    return OllamaService(get_settings())
