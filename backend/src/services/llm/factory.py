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

    Set ``LLM_PROVIDER`` in .env or environment to choose a backend:

        LLM_PROVIDER=ollama      OLLAMA_MODEL=llama3.2
        LLM_PROVIDER=anthropic   ANTHROPIC_API_KEY=sk-ant-...   ANTHROPIC_MODEL=claude-opus-4-6
        LLM_PROVIDER=openai      OPENAI_API_KEY=sk-...          OPENAI_MODEL=gpt-4o
            # Azure OpenAI / compatible endpoint:
            OPENAI_BASE_URL=https://my-resource.openai.azure.com/
    """
    settings = get_settings()
    provider = settings.llm_provider.lower()
    logger.info("llm_provider_init", provider=provider)

    if provider == "anthropic":
        from src.services.llm.anthropic import AnthropicProvider
        return AnthropicProvider(settings)

    if provider == "openai":
        from src.services.llm.openai import OpenAIProvider
        return OpenAIProvider(settings)

    # Default: Ollama (local)
    from src.services.llm.ollama import OllamaProvider
    return OllamaProvider(settings)
