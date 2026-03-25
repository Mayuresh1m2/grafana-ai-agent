"""Grafana session management endpoints.

POST /connect  — browser-login, discover datasources, store session.
GET  /datasources — return the datasource list for an active session.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.models.requests import GrafanaConnectRequest
from src.models.responses import DatasourceInfo, GrafanaConnectResponse
from src.services.grafana_auth import GrafanaAuthError, GrafanaAuthService
from src.services.session_store import GrafanaSession, SessionStore, get_session_store

logger = structlog.get_logger(__name__)
router = APIRouter()

_auth_service = GrafanaAuthService()


@router.post(
    "/connect",
    response_model=GrafanaConnectResponse,
    summary="Authenticate with Grafana and discover datasources",
    description=(
        "Uses headless Chromium to log in to the given Grafana instance, "
        "extracts the session cookie, calls /api/datasources, and stores the "
        "session for subsequent proxy queries."
    ),
    status_code=200,
)
async def connect(
    body: GrafanaConnectRequest,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> GrafanaConnectResponse:
    log = logger.bind(session_id=body.session_id, grafana_url=body.grafana_url)
    log.info("grafana_connect_request")

    # ── Browser login ──────────────────────────────────────────────────────────
    try:
        cookies = await _auth_service.authenticate(
            grafana_url=body.grafana_url,
            username=body.username,
            password=body.password,
        )
    except GrafanaAuthError as exc:
        log.warning("grafana_auth_failed", error=str(exc))
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    # ── Datasource discovery ───────────────────────────────────────────────────
    try:
        raw_datasources = await _auth_service.fetch_datasources(
            grafana_url=body.grafana_url,
            cookies=cookies,
        )
    except GrafanaAuthError as exc:
        log.warning("grafana_datasource_fetch_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    datasources = [
        DatasourceInfo(
            uid=str(ds.get("uid", "")),
            name=str(ds.get("name", "")),
            type=str(ds.get("type", "")),
            is_default=bool(ds.get("isDefault", False)),
        )
        for ds in raw_datasources
        if ds.get("uid")
    ]

    # ── Persist session ────────────────────────────────────────────────────────
    session = GrafanaSession(
        session_id=body.session_id,
        grafana_url=body.grafana_url,
        cookies=cookies,
        datasources=datasources,
    )
    await store.put(session)
    log.info("grafana_session_stored", datasource_count=len(datasources))

    return GrafanaConnectResponse(
        session_id=body.session_id,
        grafana_url=body.grafana_url,
        datasources=datasources,
    )


@router.get(
    "/datasources",
    response_model=list[DatasourceInfo],
    summary="List datasources for an active session",
)
async def list_datasources(
    session_id: str,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> list[DatasourceInfo]:
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail=f"No active session for session_id='{session_id}'. Call POST /connect first.",
        )
    return session.datasources
