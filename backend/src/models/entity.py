"""Service entity model for alias-based query enrichment."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """What kind of infrastructure entity this is."""
    service    = "service"
    namespace  = "namespace"
    database   = "database"
    deployment = "deployment"


class ServiceEntity(BaseModel):
    id:          str       = Field(default_factory=lambda: str(uuid4()))
    name:        str       = Field(..., min_length=1, max_length=200,
                                   description="Canonical name (e.g. 'reporting-processor').")
    namespace:   str       = Field(..., min_length=1, max_length=200,
                                   description="Kubernetes namespace (e.g. 'prod-services').")
    entity_type: EntityType = Field(default=EntityType.service)
    aliases:     list[str] = Field(default_factory=list,
                                   description="Natural-language aliases users might say (e.g. ['reporting', 'reports']).")
    description: str       = Field(default="")
    created_at:  datetime  = Field(default_factory=lambda: datetime.now(timezone.utc))


class EntityCreate(BaseModel):
    name:        str
    namespace:   str
    entity_type: EntityType = EntityType.service
    aliases:     list[str]  = []
    description: str        = ""


def resolve_entities(query: str, entities: list[ServiceEntity]) -> list[ServiceEntity]:
    """Return entities whose aliases appear (case-insensitive) anywhere in the query."""
    q = query.lower()
    matched: list[ServiceEntity] = []
    for entity in entities:
        for alias in entity.aliases:
            if alias.lower() in q:
                matched.append(entity)
                break  # one alias match is enough per entity
    return matched
