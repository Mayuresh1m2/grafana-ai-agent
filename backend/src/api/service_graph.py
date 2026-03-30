"""API for the service topology graph."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.models.service_graph import ServiceGraph, ServiceGraphUpdate
from src.services.service_graph_store import ServiceGraphStore, get_service_graph_store

router = APIRouter()

Dep = Annotated[ServiceGraphStore, Depends(get_service_graph_store)]


@router.get("/", response_model=ServiceGraph)
def get_graph(store: Dep) -> ServiceGraph:
    """Return the current service graph."""
    return store.load()


@router.put("/", response_model=ServiceGraph)
def save_graph(body: ServiceGraphUpdate, store: Dep) -> ServiceGraph:
    """Replace the service graph with the supplied nodes and edges."""
    return store.save(body)
