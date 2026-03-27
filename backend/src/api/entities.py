"""CRUD API for service entities (alias resolver)."""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.models.entity import EntityCreate, ServiceEntity
from src.services.entity_store import EntityStore, get_entity_store

logger = structlog.get_logger(__name__)
router = APIRouter()

Dep = Annotated[EntityStore, Depends(get_entity_store)]


@router.post("/", response_model=ServiceEntity, status_code=201)
def create_entity(body: EntityCreate, store: Dep) -> ServiceEntity:
    """Add a new service entity with aliases."""
    return store.add(body)


@router.get("/", response_model=list[ServiceEntity])
def list_entities(store: Dep) -> list[ServiceEntity]:
    """List all stored service entities."""
    return store.list_all()


@router.delete("/{id}", status_code=204)
def delete_entity(id: str, store: Dep) -> None:
    """Delete a service entity by ID."""
    if not store.delete(id):
        raise HTTPException(status_code=404, detail="Entity not found")
