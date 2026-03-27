"""Qdrant-backed store for query examples.

Vectors are stored in Qdrant; full example metadata lives as the point
payload alongside the vector — no separate relational database needed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from src.config import get_settings
from src.models.example import ExampleCreate, PlaceholderKey, QueryCategory, QueryExample
from src.services.rag.embedder import OllamaEmbedder

logger = structlog.get_logger(__name__)


class ExampleStore:
    def __init__(
        self,
        qdrant_url: str,
        collection: str,
        embedder: OllamaEmbedder,
        vector_size: int = 768,
    ) -> None:
        self._client     = QdrantClient(url=qdrant_url)
        self._collection = collection
        self._embedder   = embedder
        self._vector_size = vector_size
        self._ensure_collection()
        logger.info("example_store_ready", qdrant_url=qdrant_url,
                    collection=collection, count=self._count())

    # ── collection management ─────────────────────────────────────────────────

    def _ensure_collection(self) -> None:
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )
            logger.info("qdrant_collection_created", name=self._collection,
                        vector_size=self._vector_size)

    def _count(self) -> int:
        try:
            return self._client.count(collection_name=self._collection).count
        except Exception:
            return 0

    # ── payload helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _embed_text(example: QueryExample) -> str:
        parts = [example.description, example.title] + example.tags
        return " ".join(parts)

    @staticmethod
    def _to_payload(example: QueryExample) -> dict:
        return {
            "title":        example.title,
            "description":  example.description,
            "query_type":   example.query_type,
            "category":     example.category.value,
            "template":     example.template,
            "tags":         json.dumps(example.tags),
            "placeholders": json.dumps([p.value for p in example.placeholders]),
            "created_at":   example.created_at.isoformat(),
        }

    @staticmethod
    def _from_payload(id_: str, payload: dict) -> QueryExample:
        return QueryExample(
            id=id_,
            title=payload["title"],
            description=payload["description"],
            query_type=payload["query_type"],
            category=QueryCategory(payload.get("category", QueryCategory.service.value)),
            template=payload["template"],
            tags=json.loads(payload.get("tags", "[]")),
            placeholders=[PlaceholderKey(p) for p in json.loads(payload.get("placeholders", "[]"))],
            created_at=datetime.fromisoformat(payload["created_at"]),
        )

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def add(self, body: ExampleCreate) -> QueryExample:
        example   = QueryExample(**body.model_dump())
        embedding = await self._embedder.embed(self._embed_text(example))
        self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(
                id=example.id,
                vector=embedding,
                payload=self._to_payload(example),
            )],
        )
        logger.info("example_added", id=example.id, title=example.title)
        return example

    def list_all(self) -> list[QueryExample]:
        points, _ = self._client.scroll(
            collection_name=self._collection,
            limit=10_000,
            with_payload=True,
            with_vectors=False,
        )
        return [self._from_payload(str(p.id), p.payload or {}) for p in points]

    def get(self, id_: str) -> QueryExample | None:
        results = self._client.retrieve(
            collection_name=self._collection,
            ids=[id_],
            with_payload=True,
        )
        if not results:
            return None
        p = results[0]
        return self._from_payload(str(p.id), p.payload or {})

    def delete(self, id_: str) -> bool:
        if not self._client.retrieve(collection_name=self._collection, ids=[id_]):
            return False
        self._client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=[id_]),
        )
        logger.info("example_deleted", id=id_)
        return True

    async def search(
        self,
        query: str,
        top_k: int = 3,
        category: QueryCategory | None = None,
    ) -> list[tuple[QueryExample, float]]:
        if self._count() == 0:
            return []
        embedding = await self._embedder.embed(query)
        query_filter = (
            Filter(must=[FieldCondition(key="category", match=MatchValue(value=category.value))])
            if category else None
        )
        results = self._client.search(
            collection_name=self._collection,
            query_vector=embedding,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            (self._from_payload(str(r.id), r.payload or {}), float(r.score))
            for r in results
        ]


@lru_cache(maxsize=1)
def get_example_store() -> ExampleStore:
    settings = get_settings()
    embedder = OllamaEmbedder(settings)
    return ExampleStore(
        qdrant_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        embedder=embedder,
        vector_size=settings.embedding_vector_size,
    )
