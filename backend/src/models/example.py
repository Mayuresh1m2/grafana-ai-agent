"""Query example model for the RAG pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class QueryCategory(str, Enum):
    """What the query targets — used to filter examples by domain.
    Add new members here to support additional categories.
    """
    service        = "service"
    database       = "database"
    infrastructure = "infrastructure"
    kubernetes     = "kubernetes"
    networking     = "networking"


class QueryExample(BaseModel):
    id:             str      = Field(default_factory=lambda: str(uuid4()))
    title:          str      = Field(..., min_length=1, max_length=200)
    description:    str      = Field(..., min_length=1, max_length=1000,
                                     description="Plain-language description — this text is embedded for semantic search.")
    query_type:     str      = Field(..., pattern="^(loki|prometheus)$")
    category:       QueryCategory = Field(default=QueryCategory.service,
                                          description="What the query targets (service, database, infrastructure, …).")
    template:       str       = Field(..., min_length=1,
                                      description="Query template with {{placeholder}} tokens.")
    tags:           list[str] = Field(default_factory=list)
    placeholders:   list[str] = Field(default_factory=list,
                                      description="Placeholder names found in the template (e.g. ['namespace', 'container']).")
    created_at:     datetime  = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExampleCreate(BaseModel):
    title:        str
    description:  str
    query_type:   str = Field(..., pattern="^(loki|prometheus)$")
    category:     QueryCategory = QueryCategory.service
    template:     str
    tags:         list[str] = []
    placeholders: list[str] = []


class ExampleSearchRequest(BaseModel):
    query:   str
    context: dict[str, str] = {}
    top_k:   int = Field(default=3, ge=1, le=10)
