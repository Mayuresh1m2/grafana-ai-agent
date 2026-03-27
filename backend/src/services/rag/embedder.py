"""Ollama embedding client for the RAG pipeline."""
from __future__ import annotations

import httpx
import structlog

from src.config import Settings

logger = structlog.get_logger(__name__)


class OllamaEmbedder:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.embedding_model
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(30.0),
        )

    async def embed(self, text: str) -> list[float]:
        response = await self._client.post(
            "/api/embeddings",
            json={"model": self._model, "prompt": text},
        )
        response.raise_for_status()
        embedding: list[float] = response.json()["embedding"]
        logger.debug("embedded_text", model=self._model, dim=len(embedding), preview=text[:80])
        return embedding

    async def aclose(self) -> None:
        await self._client.aclose()
