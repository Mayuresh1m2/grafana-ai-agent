"""Session store for authenticated Grafana sessions.

Sessions are kept in memory for fast access and also written to disk so they
survive backend restarts.  Each session is a small JSON file under
``./data/sessions/``.  On first access of an unknown session_id the store
checks disk before returning None, so users don't have to re-authenticate after
a backend restart as long as their Grafana cookies are still valid.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.models.responses import DatasourceInfo

logger = structlog.get_logger(__name__)

_SESSION_DIR = Path("./data/sessions")


def _session_path(session_id: str) -> Path:
    return _SESSION_DIR / f"{session_id}.json"


def _to_dict(session: "GrafanaSession") -> dict:
    return {
        "session_id":    session.session_id,
        "grafana_url":   session.grafana_url,
        "cookies":       session.cookies,
        "datasources":   [
            {"uid": d.uid, "name": d.name, "type": d.type, "is_default": d.is_default}
            for d in session.datasources
        ],
        "service_token": session.service_token,
        "azure_scope":   session.azure_scope,
        "created_at":    session.created_at.isoformat(),
    }


def _from_dict(data: dict) -> "GrafanaSession":
    return GrafanaSession(
        session_id=data["session_id"],
        grafana_url=data["grafana_url"],
        cookies=data.get("cookies") or {},
        datasources=[
            DatasourceInfo(
                uid=d["uid"],
                name=d["name"],
                type=d["type"],
                is_default=d.get("is_default", False),
            )
            for d in data.get("datasources", [])
        ],
        service_token=data.get("service_token"),
        azure_scope=data.get("azure_scope"),
        created_at=datetime.fromisoformat(data["created_at"]),
    )


@dataclass
class GrafanaSession:
    """Everything the backend needs to proxy Grafana API calls for one user.

    Authentication is one of:
    - **Cookie-based** (``cookies`` non-empty): browser session cookie extracted
      via Playwright or pasted from the browser after Microsoft SSO.
    - **Service token** (``service_token`` non-empty): Grafana service account
      token sent as ``Authorization: Bearer <token>`` on every request.
    - **Azure CLI** (``azure_scope`` non-empty): an Azure AD Bearer token is
      fetched on each request via ``AzureCliCredential``, which reads the token
      cached by ``az login`` on the local machine and auto-refreshes it.
    """

    session_id: str
    grafana_url: str
    cookies: dict[str, str]
    datasources: list[DatasourceInfo]
    service_token: str | None = None  # Grafana service account token (glsa_...)
    azure_scope: str | None = None    # e.g. "api://<grafana-app-client-id>/.default"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def cookie_header(self) -> str:
        """Return a ``Cookie:`` header value for httpx requests."""
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


class SessionStore:
    """Asyncio-safe session store — memory-backed with disk persistence.

    Writes each session to ``./data/sessions/<session_id>.json`` on ``put`` and
    loads from disk on a cache miss in ``get``, so sessions survive backend
    restarts as long as the Grafana cookies are still valid.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, GrafanaSession] = {}
        self._lock = asyncio.Lock()
        _SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # ── disk helpers (called with lock held) ──────────────────────────────────

    def _save(self, session: GrafanaSession) -> None:
        try:
            path = _session_path(session.session_id)
            path.write_text(json.dumps(_to_dict(session), indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("session_disk_save_failed", session_id=session.session_id, error=str(exc))

    def _load_from_disk(self, session_id: str) -> GrafanaSession | None:
        path = _session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _from_dict(data)
        except Exception as exc:
            logger.warning("session_disk_load_failed", session_id=session_id, error=str(exc))
            return None

    def _delete_from_disk(self, session_id: str) -> None:
        try:
            _session_path(session_id).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("session_disk_delete_failed", session_id=session_id, error=str(exc))

    # ── public API ────────────────────────────────────────────────────────────

    async def put(self, session: GrafanaSession) -> None:
        async with self._lock:
            self._sessions[session.session_id] = session
            self._save(session)
        logger.info(
            "session_stored",
            session_id=session.session_id,
            datasource_count=len(session.datasources),
        )

    async def get(self, session_id: str) -> GrafanaSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                # Cache miss — try to restore from disk (backend restart case)
                session = self._load_from_disk(session_id)
                if session:
                    self._sessions[session_id] = session
                    logger.info("session_restored_from_disk", session_id=session_id)
            return session

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            removed = self._sessions.pop(session_id, None)
            self._delete_from_disk(session_id)
        if removed:
            logger.info("session_deleted", session_id=session_id)

    def __len__(self) -> int:
        return len(self._sessions)


# Module-level singleton — injected via FastAPI Depends
_store = SessionStore()


def get_session_store() -> SessionStore:
    """FastAPI dependency that returns the singleton SessionStore."""
    return _store
