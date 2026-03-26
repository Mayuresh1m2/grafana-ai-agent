"""Provider factory — single place to change the active LLM backend."""
from __future__ import annotations

from functools import lru_cache

import structlog

from src.config import get_settings
from src.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Return a cached LLMProvider instance driven entirely by config.

    To switch provider, set in .env or environment:
        LLM_PROVIDER=anthropic   ANTHROPIC_API_KEY=sk-ant-...
        LLM_PROVIDER=ollama      OLLAMA_MODEL=llama3.2
    """
    settings = get_settings()
    provider = settings.llm_provider.lower()
    logger.info("llm_provider_init", provider=provider)

    if provider == "anthropic":
        from src.services.llm.anthropic import AnthropicProvider
        return AnthropicProvider(settings)

    # Default: Ollama
    from src.services.llm.ollama import OllamaProvider
    return OllamaProvider(settings)
