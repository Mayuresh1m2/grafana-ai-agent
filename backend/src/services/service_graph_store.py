"""File-backed store for the service graph.

The graph is persisted as a pretty-printed JSON file so teams can commit it
to their project repository alongside other configuration.  The file path is
configurable via ``SERVICE_GRAPH_PATH`` in the environment / .env file.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import structlog

from src.config import get_settings
from src.models.service_graph import ServiceGraph, ServiceGraphUpdate

logger = structlog.get_logger(__name__)


class ServiceGraphStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> ServiceGraph:
        if not self._path.exists():
            logger.debug("service_graph_file_not_found", path=str(self._path))
            return ServiceGraph()
        try:
            return ServiceGraph.model_validate_json(self._path.read_text())
        except Exception as exc:
            logger.warning("service_graph_load_error", path=str(self._path), error=str(exc))
            return ServiceGraph()

    def save(self, update: ServiceGraphUpdate) -> ServiceGraph:
        graph = ServiceGraph(
            nodes=update.nodes,
            edges=update.edges,
            updated_at=datetime.now(timezone.utc),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(graph.model_dump_json(indent=2))
        logger.info("service_graph_saved", path=str(self._path),
                    nodes=len(graph.nodes), edges=len(graph.edges))
        return graph


@lru_cache(maxsize=1)
def get_service_graph_store() -> ServiceGraphStore:
    settings = get_settings()
    return ServiceGraphStore(Path(settings.service_graph_path))
