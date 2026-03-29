"""CRUD API for query examples (RAG store)."""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from src.models.example import ExampleCreate, ExampleSearchRequest, QueryExample
from src.services.rag.store import ExampleStore, get_example_store

logger = structlog.get_logger(__name__)
router = APIRouter()


def _store_dep(grafana_url: str = Query(default="")) -> ExampleStore:
    """FastAPI dependency — resolves the ExampleStore for the given Grafana instance."""
    return get_example_store(grafana_url)


Dep = Annotated[ExampleStore, Depends(_store_dep)]


@router.post("/", response_model=QueryExample, status_code=201)
async def create_example(body: ExampleCreate, store: Dep) -> QueryExample:
    """Add a new query example to the RAG store."""
    return await store.add(body)


@router.get("/", response_model=list[QueryExample])
def list_examples(store: Dep) -> list[QueryExample]:
    """List all stored query examples."""
    return store.list_all()


@router.delete("/{id}", status_code=204)
def delete_example(id: str, store: Dep) -> None:
    """Delete a query example by ID."""
    if not store.delete(id):
        raise HTTPException(status_code=404, detail="Example not found")


@router.post("/search", response_model=list[QueryExample])
async def search_examples(body: ExampleSearchRequest, store: Dep) -> list[QueryExample]:
    """Semantic search — useful for testing retrieval from the UI."""
    hits = await store.search(body.query, top_k=body.top_k)
    return [ex for ex, _ in hits]
