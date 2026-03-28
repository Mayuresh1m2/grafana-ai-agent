"""Grafana session management endpoints.

POST /connect     — authenticate (credentials, cookie relay, or Azure CLI) and discover datasources.
POST /refresh     — replace an expired session cookie without re-running the full flow.
GET  /datasources — return the datasource list for an active session.
GET  /alerts      — return currently firing alerts.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.models.requests import GrafanaConnectRequest, GrafanaRefreshRequest, GrafanaSsoBrowserRequest
from src.models.responses import AlertInfo, DatasourceInfo, GrafanaConnectResponse
from src.services.grafana import GrafanaClient
from src.services.grafana_auth import GrafanaAuthError, GrafanaAuthService
from src.services.session_store import GrafanaSession, SessionStore, get_session_store

logger = structlog.get_logger(__name__)
router = APIRouter()

_auth_service = GrafanaAuthService()


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_cookie_header(raw: str) -> dict[str, str]:
    """Parse a browser Cookie header string into a name→value dict."""
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
    """Validate *cookies* against /api/datasources and return the datasource list."""
    tentative = GrafanaSession(
        session_id="",
        grafana_url=grafana_url,
        cookies=cookies,
        datasources=[],
    )
    try:
        client = await GrafanaClient.create(tentative)
        try:
            return await client.fetch_datasources_from_api()
        finally:
            await client.aclose()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch datasources: {exc}") from exc


async def _probe_and_store(
    body: GrafanaConnectRequest,
    store: SessionStore,
    log: structlog.BoundLogger,
    *,
    azure_scope: str | None = None,
    service_token: str | None = None,
    error_detail: str,
) -> GrafanaConnectResponse:
    """Validate credentials by probing the Grafana API, then persist the session.

    Used by both the Azure CLI and service-token auth paths, which share
    identical probe → validate → store → respond logic.
    """
    tentative = GrafanaSession(
        session_id=body.session_id,
        grafana_url=body.grafana_url,
        cookies={},
        datasources=[],
        azure_scope=azure_scope,
        service_token=service_token,
    )
    try:
        client = await GrafanaClient.create(tentative)
        datasources = await client.fetch_datasources_from_api()
        await client.aclose()
    except HTTPException:
        raise
    except Exception as exc:
        auth_mode = "azure" if azure_scope else "token"
        log.warning("grafana_connect_failed", auth_mode=auth_mode, error=str(exc))
        raise HTTPException(status_code=401, detail=f"{error_detail}: {exc}") from exc

    log.info("grafana_datasources_discovered", count=len(datasources))
    await store.put(GrafanaSession(
        session_id=body.session_id,
        grafana_url=body.grafana_url,
        cookies={},
        datasources=datasources,
        azure_scope=azure_scope,
        service_token=service_token,
    ))
    return GrafanaConnectResponse(
        session_id=body.session_id,
        grafana_url=body.grafana_url,
        datasources=datasources,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/connect",
    response_model=GrafanaConnectResponse,
    summary="Authenticate with Grafana and discover datasources",
    description=(
        "Four authentication modes:\n"
        "1. **Credentials** (username + password) — headless Playwright login.\n"
        "2. **Cookie relay** (cookie_header) — user completes SSO in their browser and pastes the Cookie header.\n"
        "3. **Service token** (service_token) — Grafana service account token.\n"
        "4. **Azure CLI** (azure_scope) — Bearer token via local `az login` cache."
    ),
    status_code=200,
)
async def connect(
    body: GrafanaConnectRequest,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> GrafanaConnectResponse:
    log = logger.bind(session_id=body.session_id, grafana_url=body.grafana_url)

    has_credentials = bool(body.username and body.password)
    has_cookie      = bool(body.cookie_header)
    has_azure       = bool(body.azure_scope)
    has_token       = bool(body.service_token)

    if not (has_credentials or has_cookie or has_azure or has_token):
        raise HTTPException(
            status_code=422,
            detail="Provide one of: (username + password), cookie_header, service_token, or azure_scope.",
        )

    if has_azure:
        log.info("grafana_connect_azure_cli")
        return await _probe_and_store(
            body, store, log,
            azure_scope=body.azure_scope,
            error_detail="Azure CLI auth failed. Make sure 'az login' is completed and the scope is correct",
        )

    if has_token:
        log.info("grafana_connect_service_token")
        return await _probe_and_store(
            body, store, log,
            service_token=body.service_token,
            error_detail="Token auth failed",
        )

    # Cookie / credentials path
    if has_cookie:
        log.info("grafana_connect_cookie_relay")
        cookies = _parse_cookie_header(body.cookie_header)  # type: ignore[arg-type]
    else:
        log.info("grafana_connect_credentials")
        try:
            cookies = await _auth_service.authenticate(
                grafana_url=body.grafana_url,
                username=body.username,    # type: ignore[arg-type]
                password=body.password,    # type: ignore[arg-type]
            )
        except GrafanaAuthError as exc:
            log.warning("grafana_auth_failed", error=str(exc))
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    datasources = await _discover_datasources(body.grafana_url, cookies)
    log.info("grafana_datasources_discovered", count=len(datasources))

    await store.put(GrafanaSession(
        session_id=body.session_id,
        grafana_url=body.grafana_url,
        cookies=cookies,
        datasources=datasources,
    ))
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
    datasources = await _discover_datasources(session.grafana_url, cookies)

    session.cookies = cookies
    session.datasources = datasources
    await store.put(session)
    log.info("grafana_session_refreshed", datasource_count=len(datasources))

    return GrafanaConnectResponse(
        session_id=body.session_id,
        grafana_url=session.grafana_url,
        datasources=datasources,
    )


@router.post(
    "/reauth",
    response_model=GrafanaConnectResponse,
    summary="Re-authenticate with Grafana via a headed SSO browser window",
    description=(
        "Opens a visible Chromium window so the user can complete SSO without "
        "manually copying cookies.  Works for both the initial connect flow and "
        "session refresh after a cookie expires.  The call blocks until the user "
        "finishes login (up to 3 minutes) then captures all cookies automatically."
    ),
    status_code=200,
)
async def reauth(
    body: GrafanaSsoBrowserRequest,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> GrafanaConnectResponse:
    log = logger.bind(session_id=body.session_id)

    existing = await store.get(body.session_id)
    grafana_url = body.grafana_url or (existing.grafana_url if existing else None)
    if not grafana_url:
        raise HTTPException(
            status_code=422,
            detail="grafana_url is required when no existing session is found.",
        )

    log.info("grafana_reauth_sso_browser", grafana_url=grafana_url)
    try:
        cookies = await _auth_service.reauth_sso(grafana_url)
    except GrafanaAuthError as exc:
        log.warning("grafana_reauth_sso_failed", error=str(exc))
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    datasources = await _discover_datasources(grafana_url, cookies)
    log.info("grafana_reauth_sso_success", datasource_count=len(datasources))

    await store.put(GrafanaSession(
        session_id=body.session_id,
        grafana_url=grafana_url,
        cookies=cookies,
        datasources=datasources,
    ))
    return GrafanaConnectResponse(
        session_id=body.session_id,
        grafana_url=grafana_url,
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
    client = await GrafanaClient.create(session)
    try:
        return await client.get_active_alerts()
    finally:
        await client.aclose()
