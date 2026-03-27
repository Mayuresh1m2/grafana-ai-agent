"""SQLite-backed store for service entities."""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

import structlog

from src.config import get_settings
from src.models.entity import EntityCreate, ServiceEntity

logger = structlog.get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    namespace   TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT 'service',
    aliases     TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
"""


class EntityStore:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_DDL)
        self._conn.commit()
        logger.info("entity_store_ready", db_path=db_path, count=self._count())

    # ── helpers ───────────────────────────────────────────────────────────────

    def _count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> ServiceEntity:
        return ServiceEntity.model_validate({
            "id":          row["id"],
            "name":        row["name"],
            "namespace":   row["namespace"],
            "entity_type": row["entity_type"],
            "aliases":     json.loads(row["aliases"]),
            "description": row["description"],
            "created_at":  row["created_at"],
        })

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add(self, body: EntityCreate) -> ServiceEntity:
        entity = ServiceEntity(**body.model_dump())
        self._conn.execute(
            """
            INSERT OR REPLACE INTO entities
                (id, name, namespace, entity_type, aliases, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity.id,
                entity.name,
                entity.namespace,
                entity.entity_type.value,
                json.dumps(entity.aliases),
                entity.description,
                entity.created_at.isoformat(),
            ),
        )
        self._conn.commit()
        logger.info("entity_added", id=entity.id, name=entity.name)
        return entity

    def list_all(self) -> list[ServiceEntity]:
        rows = self._conn.execute(
            "SELECT * FROM entities ORDER BY name"
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def get(self, id_: str) -> ServiceEntity | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = ?", (id_,)
        ).fetchone()
        return self._row_to_entity(row) if row else None

    def delete(self, id_: str) -> bool:
        if not self.get(id_):
            return False
        self._conn.execute("DELETE FROM entities WHERE id = ?", (id_,))
        self._conn.commit()
        logger.info("entity_deleted", id=id_)
        return True


@lru_cache(maxsize=1)
def get_entity_store() -> EntityStore:
    settings = get_settings()
    return EntityStore(db_path=settings.sqlite_db_path)
