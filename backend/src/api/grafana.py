"""Grafana session management endpoints.

POST /connect  — authenticate (credentials or cookie relay) and discover datasources.
POST /refresh  — replace an expired session cookie without re-running the full flow.
GET  /datasources — return the datasource list for an active session.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.models.requests import GrafanaConnectRequest, GrafanaRefreshRequest
from src.models.responses import AlertInfo, DatasourceInfo, GrafanaConnectResponse
from src.services.grafana_auth import GrafanaAuthError, GrafanaAuthService
from src.services.grafana import GrafanaClient
from src.services.session_store import GrafanaSession, SessionStore, get_session_store

logger = structlog.get_logger(__name__)
router = APIRouter()

_auth_service = GrafanaAuthService()


def _parse_cookie_header(raw: str) -> dict[str, str]:
    """Parse a browser Cookie header string into a name→value dict.

    Handles the common formats:
      - ``key=value; key2=value2``
      - values that themselves contain ``=`` (base64 etc.)
    """
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cookies[name.strip()] = value.strip()
    return cookies


async def _discover_datasources(
    grafana_url: str,
    cookies: dict[str, str],
) -> list[DatasourceInfo]:
    """Call /api/datasources and convert to DatasourceInfo list."""
    try:
        raw = await _auth_service.fetch_datasources(grafana_url, cookies)
    except GrafanaAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return [
        DatasourceInfo(
            uid=str(ds.get("uid", "")),
            name=str(ds.get("name", "")),
            type=str(ds.get("type", "")),
            is_default=bool(ds.get("isDefault", False)),
        )
        for ds in raw
        if ds.get("uid")
    ]


@router.post(
    "/connect",
    response_model=GrafanaConnectResponse,
    summary="Authenticate with Grafana and discover datasources",
    description=(
        "Two modes:\n"
        "1. **Credentials** (username + password) — headless Playwright login.\n"
        "2. **Cookie relay** (cookie_header) — user completes Microsoft SSO in their "
        "own browser and pastes the Cookie header. The backend validates it by calling "
        "/api/datasources before storing the session."
    ),
    status_code=200,
)
async def connect(
    body: GrafanaConnectRequest,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> GrafanaConnectResponse:
    log = logger.bind(session_id=body.session_id, grafana_url=body.grafana_url)

    has_credentials = body.username and body.password
    has_cookie = bool(body.cookie_header)

    if not has_credentials and not has_cookie:
        raise HTTPException(
            status_code=422,
            detail="Provide either (username + password) or cookie_header.",
        )

    # ── Resolve cookies ────────────────────────────────────────────────────────
    if has_cookie:
        log.info("grafana_connect_cookie_relay")
        cookies = _parse_cookie_header(body.cookie_header)  # type: ignore[arg-type]
    else:
        log.info("grafana_connect_credentials")
        try:
            cookies = await _auth_service.authenticate(
                grafana_url=body.grafana_url,
                username=body.username,  # type: ignore[arg-type]
                password=body.password,  # type: ignore[arg-type]
            )
        except GrafanaAuthError as exc:
            log.warning("grafana_auth_failed", error=str(exc))
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    # ── Validate + discover datasources ───────────────────────────────────────
    datasources = await _discover_datasources(body.grafana_url, cookies)
    log.info("grafana_datasources_discovered", count=len(datasources))

    # ── Persist session ────────────────────────────────────────────────────────
    await store.put(
        GrafanaSession(
            session_id=body.session_id,
            grafana_url=body.grafana_url,
            cookies=cookies,
            datasources=datasources,
        )
    )

    return GrafanaConnectResponse(
        session_id=body.session_id,
        grafana_url=body.grafana_url,
        datasources=datasources,
    )


@router.post(
    "/refresh",
    response_model=GrafanaConnectResponse,
    summary="Refresh an expired Grafana session cookie",
    description=(
        "Replaces the cookie on an existing session without re-running the full setup. "
        "Call this when the agent signals that the session has expired (HTTP 401 with "
        "code='session_expired'). The user pastes a fresh Cookie header after "
        "re-logging in via the Microsoft SSO popup."
    ),
    status_code=200,
)
async def refresh(
    body: GrafanaRefreshRequest,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> GrafanaConnectResponse:
    log = logger.bind(session_id=body.session_id)
    log.info("grafana_refresh_request")

    session = await store.get(body.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"No session found for session_id='{body.session_id}'. Use POST /connect first.",
        )

    cookies = _parse_cookie_header(body.cookie_header)

    # Validate the new cookie before storing
    datasources = await _discover_datasources(session.grafana_url, cookies)

    # Replace cookies in-place; keep grafana_url and datasources (re-discovered above)
    session.cookies = cookies
    session.datasources = datasources
    await store.put(session)
    log.info("grafana_session_refreshed", datasource_count=len(datasources))

    return GrafanaConnectResponse(
        session_id=body.session_id,
        grafana_url=session.grafana_url,
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


@router.get(
    "/alerts",
    response_model=list[AlertInfo],
    summary="Return currently firing Grafana alerts",
    description=(
        "Tries the Alertmanager v2 API first (Grafana unified alerting, v8+), "
        "then falls back to the legacy /api/alerts endpoint. "
        "Returns an empty list rather than an error when neither is available."
    ),
)
async def get_alerts(
    session_id: str,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> list[AlertInfo]:
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail=f"No active session for session_id='{session_id}'. Call POST /connect first.",
        )
    client = GrafanaClient(session)
    try:
        return await client.get_active_alerts()
    finally:
        await client.aclose()
