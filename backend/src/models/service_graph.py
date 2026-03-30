"""Data models for the service graph (topology map)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    service = "service"
    topic = "topic"
    queue = "queue"
    database = "database"
    external = "external"


class EdgeType(str, Enum):
    rest = "rest"
    grpc = "grpc"
    publish = "publish"
    subscribe = "subscribe"
    reads = "reads"
    writes = "writes"
    calls = "calls"


class GraphNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    node_type: NodeType = NodeType.service
    name: str
    description: str = ""
    tech: str = ""          # e.g. "Python/FastAPI", "Kafka", "PostgreSQL"
    position_x: float = 0.0
    position_y: float = 0.0


class GraphEdge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str             # node id
    target: str             # node id
    edge_type: EdgeType = EdgeType.rest
    label: str = ""


class ServiceGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ServiceGraphUpdate(BaseModel):
    """Full replacement payload from the frontend editor."""
    nodes: list[GraphNode]
    edges: list[GraphEdge]
