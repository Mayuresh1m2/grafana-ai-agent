"""Abstract LLM provider interface and shared output utilities."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

# Appended to system prompts to instruct the model to emit follow-up suggestions.
SUGGESTIONS_INSTRUCTION = (
    "\n\nAfter your answer, on its own line, append exactly this (valid JSON array, "
    "no trailing text):\n"
    'SUGGESTIONS: ["follow-up question 1?", "follow-up question 2?", "follow-up question 3?"]\n'
    "The questions should be 2-3 concise things an on-call engineer would naturally investigate next. "
    "Do not include any text after the SUGGESTIONS line."
)


def parse_suggestions(text: str) -> tuple[str, list[str]]:
    """Split LLM output into ``(clean_answer, suggestions_list)``.

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


class LLMProvider(ABC):
    """Common interface for all LLM backends (Ollama, Anthropic, …)."""

    @property
    @abstractmethod
    def default_model(self) -> str:
        """The provider's default model name."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """Single-turn chat with optional tool calling.

        Args:
            messages:    Conversation history in Ollama-compatible format:
                         role ∈ {system, user, assistant, tool}
                         assistant messages may carry ``tool_calls``
                         tool messages carry the result string in ``content``
            tools:       Ollama-compatible tool schemas (type=function wrappers).
            model:       Override the provider default.
            temperature: Sampling temperature.
            max_tokens:  Maximum tokens in the response.

        Returns:
            Message dict with ``content`` (str) and/or
            ``tool_calls`` (list[dict]) in Ollama format.
        """

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system: str,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Stream a completion token-by-token (for report generation)."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return model names available from this provider."""
