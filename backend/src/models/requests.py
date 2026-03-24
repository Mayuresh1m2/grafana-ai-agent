"""Inbound request models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentQueryRequest(BaseModel):
    """Request body for POST /api/v1/agent/query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        description="Natural-language question for the AI agent.",
        examples=["What is the p99 latency of the checkout service over the last hour?"],
    )
    context: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional key-value context injected into the system prompt. "
            "E.g. {'dashboard': 'checkout', 'environment': 'production'}."
        ),
    )
    model: str | None = Field(
        default=None,
        description="Ollama model name. Falls back to OLLAMA_MODEL env var when null.",
        examples=["llama3", "mistral", "phi3"],
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0 = deterministic, 2 = very random).",
    )
    max_tokens: int = Field(
        default=2048,
        ge=1,
        le=8192,
        description="Maximum number of tokens in the response.",
    )
