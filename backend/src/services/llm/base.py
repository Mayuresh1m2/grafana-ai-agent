"""Abstract LLM provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


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
    ) -> dict:
        """Single-turn chat with optional tool calling.

        Args:
            messages: Conversation history in Ollama-compatible format:
                      role ∈ {system, user, assistant, tool}
                      assistant messages may have ``tool_calls``
                      tool messages carry the result string in ``content``
            tools:    Ollama-compatible tool schemas (type=function wrappers).
            model:    Override the provider default.
            temperature: Sampling temperature.

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
