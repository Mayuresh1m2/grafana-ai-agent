"""ChromaDB-backed store for query examples."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

import chromadb
import structlog

from src.config import get_settings
from src.models.example import ExampleCreate, PlaceholderKey, QueryCategory, QueryExample
from src.services.rag.embedder import OllamaEmbedder

logger = structlog.get_logger(__name__)

_COLLECTION = "query_examples"


class ExampleStore:
    def __init__(self, db_path: str, embedder: OllamaEmbedder) -> None:
        self._chroma = chromadb.PersistentClient(path=db_path)
        self._col    = self._chroma.get_or_create_collection(
            name=_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedder = embedder
        logger.info("example_store_ready", path=db_path, count=self._col.count())

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _embed_text(example: QueryExample) -> str:
        """Text that gets embedded — description + title + tags."""
        parts = [example.description, example.title] + example.tags
        return " ".join(parts)

    @staticmethod
    def _to_metadata(example: QueryExample) -> dict:
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
    def _from_metadata(id: str, meta: dict) -> QueryExample:
        return QueryExample(
            id=id,
            title=meta["title"],
            description=meta["description"],
            query_type=meta["query_type"],
            category=QueryCategory(meta.get("category", QueryCategory.service.value)),
            template=meta["template"],
            tags=json.loads(meta.get("tags", "[]")),
            placeholders=[PlaceholderKey(p) for p in json.loads(meta.get("placeholders", "[]"))],
            created_at=datetime.fromisoformat(meta["created_at"]),
        )

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def add(self, body: ExampleCreate) -> QueryExample:
        example = QueryExample(**body.model_dump())
        embedding = await self._embedder.embed(self._embed_text(example))
        self._col.add(
            ids=[example.id],
            embeddings=[embedding],
            documents=[self._embed_text(example)],
            metadatas=[self._to_metadata(example)],
        )
        logger.info("example_added", id=example.id, title=example.title)
        return example

    def list_all(self) -> list[QueryExample]:
        if self._col.count() == 0:
            return []
        result = self._col.get(include=["metadatas"])
        return [
            self._from_metadata(id_, meta)
            for id_, meta in zip(result["ids"], result["metadatas"])
        ]

    def get(self, id_: str) -> QueryExample | None:
        result = self._col.get(ids=[id_], include=["metadatas"])
        if not result["ids"]:
            return None
        return self._from_metadata(result["ids"][0], result["metadatas"][0])

    def delete(self, id_: str) -> bool:
        if not self._col.get(ids=[id_])["ids"]:
            return False
        self._col.delete(ids=[id_])
        logger.info("example_deleted", id=id_)
        return True

    async def search(
        self,
        query: str,
        top_k: int = 3,
        category: QueryCategory | None = None,
    ) -> list[tuple[QueryExample, float]]:
        count = self._col.count()
        if count == 0:
            return []
        k = min(top_k, count)
        embedding = await self._embedder.embed(query)
        where = {"category": {"$eq": category.value}} if category else None
        results = self._col.query(
            query_embeddings=[embedding],
            n_results=k,
            include=["metadatas", "distances"],
            where=where,
        )
        out = []
        for id_, meta, dist in zip(
            results["ids"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            score = 1.0 - float(dist)   # cosine distance → similarity
            out.append((self._from_metadata(id_, meta), score))
        return out


@lru_cache(maxsize=1)
def get_example_store() -> ExampleStore:
    settings = get_settings()
    embedder = OllamaEmbedder(settings)
    return ExampleStore(db_path=settings.chroma_db_path, embedder=embedder)
