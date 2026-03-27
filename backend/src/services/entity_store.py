"""JSON-file-backed store for service entities."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import structlog

from src.config import get_settings
from src.models.entity import EntityCreate, ServiceEntity

logger = structlog.get_logger(__name__)


class EntityStore:
    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entities: dict[str, ServiceEntity] = {}
        self._load()
        logger.info("entity_store_ready", path=str(self._path), count=len(self._entities))

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for item in raw:
                e = ServiceEntity.model_validate(item)
                self._entities[e.id] = e
        except Exception as exc:
            logger.warning("entity_store_load_error", error=str(exc))

    def _save(self) -> None:
        data = [e.model_dump(mode="json") for e in self._entities.values()]
        self._path.write_text(json.dumps(data, indent=2, default=str))

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add(self, body: EntityCreate) -> ServiceEntity:
        entity = ServiceEntity(**body.model_dump())
        self._entities[entity.id] = entity
        self._save()
        logger.info("entity_added", id=entity.id, name=entity.name)
        return entity

    def list_all(self) -> list[ServiceEntity]:
        return list(self._entities.values())

    def get(self, id_: str) -> ServiceEntity | None:
        return self._entities.get(id_)

    def delete(self, id_: str) -> bool:
        if id_ not in self._entities:
            return False
        del self._entities[id_]
        self._save()
        logger.info("entity_deleted", id=id_)
        return True


@lru_cache(maxsize=1)
def get_entity_store() -> EntityStore:
    settings = get_settings()
    return EntityStore(file_path=settings.entities_file_path)
