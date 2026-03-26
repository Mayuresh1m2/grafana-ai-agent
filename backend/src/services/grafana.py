"""Grafana HTTP client — supports cookie auth and Azure CLI Bearer auth.

All Loki and Prometheus queries are routed through the Grafana datasource proxy
(``/api/datasources/proxy/uid/{uid}/...``).

Two authentication modes:
- **Cookie** (default): browser session cookie from Playwright login or SSO relay.
- **Azure CLI**: Azure AD Bearer token fetched via ``AzureCliCredential``, which
  reads the token cached by ``az login`` on the local machine.  Token refresh
  is handled automatically by the credential — no user interaction needed.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import httpx
import structlog
from fastapi import Depends, HTTPException

from src.models.responses import AlertInfo, DatasourceInfo
from src.services.session_store import GrafanaSession, SessionStore, get_session_store

logger = structlog.get_logger(__name__)

_DATASOURCE_PROXY = "/api/datasources/proxy/uid/{uid}"


def _proxy_path(uid: str, backend_path: str) -> str:
    """Build the Grafana datasource proxy URL for a given backend path."""
    return f"{_DATASOURCE_PROXY.format(uid=uid)}{backend_path}"


def _raise_for_status(resp: httpx.Response) -> None:
    """Like resp.raise_for_status() but converts 401/403 to a structured 401.

    A 401 from Grafana means the session cookie has expired.  We raise an
    HTTPException with ``code="session_expired"`` so the frontend can prompt
    the user to re-paste their cookie rather than showing a generic error.
    """
    if resp.status_code in (401, 403):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "session_expired",
                "message": (
                    "Grafana session has expired. "
                    "Please re-authenticate via POST /api/v1/grafana/refresh."
                ),
            },
        )
    resp.raise_for_status()


class GrafanaClient:
    """Thin async wrapper around the Grafana REST API + datasource proxy.

    Do not construct directly — use the async factory :meth:`create` so that
    Azure CLI token fetching (which is synchronous) is handled off the event loop.
    """

    def __init__(self, session: GrafanaSession, auth_header: dict[str, str]) -> None:
        self._session = session
        self._http = httpx.AsyncClient(
            base_url=session.grafana_url,
            headers={**auth_header, "Accept": "application/json"},
            verify=False,  # noqa: S501 — same tolerance as browser login
            timeout=60.0,
        )

    @classmethod
    async def create(cls, session: GrafanaSession) -> "GrafanaClient":
        """Async factory — resolves auth credentials before building the client."""
        if session.azure_scope:
            auth_header = await cls._azure_bearer(session.azure_scope)
        elif session.service_token:
            auth_header = {"Authorization": f"Bearer {session.service_token}"}
        else:
            auth_header = {"Cookie": session.cookie_header()}
        return cls(session, auth_header)

    @staticmethod
    async def _azure_bearer(scope: str) -> dict[str, str]:
        """Fetch an Azure AD Bearer token via the local ``az login`` cache."""
        from azure.identity import AzureCliCredential  # lazy import — optional dep

        def _get() -> str:
            token = AzureCliCredential().get_token(scope)
            return token.token

        access_token = await asyncio.to_thread(_get)
        return {"Authorization": f"Bearer {access_token}"}

    # ── Datasource helpers ─────────────────────────────────────────────────────

    async def fetch_datasources_from_api(self) -> list[DatasourceInfo]:
        """Call ``GET /api/datasources`` using this client's credentials.

        Used during the connect flow to validate credentials and discover
        datasources without going through the auth service.
        """
        resp = await self._http.get("/api/datasources")
        _raise_for_status(resp)
        raw: list[dict[str, object]] = resp.json()
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

    # ── Cached datasource helpers ──────────────────────────────────────────────

    def get_datasources(self) -> list[DatasourceInfo]:
        """Return the datasource list cached at login time."""
        return self._session.datasources

    def find_datasource(self, ds_type: str) -> DatasourceInfo | None:
        """Return the first datasource matching *ds_type* (e.g. ``"loki"``).

        Prefers the default datasource when multiple instances of the same
        type are configured.
        """
        matches = [d for d in self._session.datasources if d.type == ds_type]
        if not matches:
            return None
        default = next((d for d in matches if d.is_default), None)
        return default or matches[0]

    def require_datasource(self, ds_type: str) -> DatasourceInfo:
        """Like :meth:`find_datasource` but raises ``HTTPException`` when absent."""
        ds = self.find_datasource(ds_type)
        if ds is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No '{ds_type}' datasource found in Grafana. "
                    "Check that it is configured in this Grafana instance."
                ),
            )
        return ds

    # ── Loki queries (via Grafana datasource proxy) ───────────────────────────

    async def query_loki(
        self,
        logql: str,
        start: str = "now-1h",
        end: str = "now",
        limit: int = 100,
        datasource_uid: str | None = None,
    ) -> dict[str, object]:
        """Execute a LogQL range query proxied through Grafana.

        Args:
            logql: LogQL expression.
            start: Range start (Loki duration string or RFC3339).
            end: Range end.
            limit: Maximum number of log lines to return.
            datasource_uid: Explicit Grafana datasource UID.  Falls back to
                the first configured Loki datasource.
        """
        uid = datasource_uid or self.require_datasource("loki").uid
        log = logger.bind(datasource_uid=uid, logql_preview=logql[:60])
        log.debug("loki_query_start")

        params = {
            "query": logql,
            "start": start,
            "end": end,
            "limit": str(limit),
        }
        resp = await self._http.get(
            _proxy_path(uid, "/loki/api/v1/query_range"), params=params
        )
        _raise_for_status(resp)
        result: dict[str, object] = resp.json()
        log.debug("loki_query_done")
        return result

    async def get_loki_label_values(
        self,
        label_name: str,
        selector: str | None = None,
        start: str = "now-6h",
        end: str = "now",
        datasource_uid: str | None = None,
    ) -> list[str]:
        """Return all values for a Loki label proxied through Grafana."""
        uid = datasource_uid or self.require_datasource("loki").uid
        params: dict[str, str] = {"start": start, "end": end}
        if selector:
            params["query"] = selector

        resp = await self._http.get(
            _proxy_path(uid, f"/loki/api/v1/label/{label_name}/values"),
            params=params,
        )
        _raise_for_status(resp)
        data: dict[str, object] = resp.json()
        values: list[str] = data.get("data", [])  # type: ignore[assignment]
        return values

    # ── Prometheus queries (via Grafana datasource proxy) ─────────────────────

    async def query_prometheus(
        self,
        promql: str,
        time: str | None = None,
        datasource_uid: str | None = None,
    ) -> dict[str, object]:
        """Execute a PromQL instant query proxied through Grafana."""
        uid = datasource_uid or self.require_datasource("prometheus").uid
        log = logger.bind(datasource_uid=uid, promql_preview=promql[:60])
        log.debug("prometheus_query_start")

        params: dict[str, str] = {"query": promql}
        if time:
            params["time"] = time

        resp = await self._http.get(
            _proxy_path(uid, "/api/v1/query"), params=params
        )
        _raise_for_status(resp)
        result: dict[str, object] = resp.json()
        log.debug("prometheus_query_done")
        return result

    async def query_prometheus_range(
        self,
        promql: str,
        start: str,
        end: str,
        step: str = "60s",
        datasource_uid: str | None = None,
    ) -> dict[str, object]:
        """Execute a PromQL range query proxied through Grafana."""
        uid = datasource_uid or self.require_datasource("prometheus").uid
        params: dict[str, str] = {
            "query": promql,
            "start": start,
            "end": end,
            "step": step,
        }
        resp = await self._http.get(
            _proxy_path(uid, "/api/v1/query_range"), params=params
        )
        _raise_for_status(resp)
        result: dict[str, object] = resp.json()
        return result

    # ── Active alerts ─────────────────────────────────────────────────────────

    async def get_active_alerts(self) -> list[AlertInfo]:
        """Return currently firing alerts.

        Tries the Grafana Alertmanager v2 API first (unified alerting, v8+).
        Falls back to the legacy ``/api/alerts`` endpoint for older instances.
        Returns an empty list if neither succeeds — alerts are best-effort.
        """
        try:
            resp = await self._http.get(
                "/api/alertmanager/grafana/api/v2/alerts",
                params={"active": "true", "silenced": "false", "inhibited": "false"},
            )
            if resp.status_code == 200:
                return self._parse_alertmanager_v2(resp.json())
        except Exception:
            pass

        try:
            resp = await self._http.get("/api/alerts", params={"state": "alerting"})
            if resp.status_code == 200:
                return self._parse_legacy_alerts(resp.json())
        except Exception:
            pass

        return []

    @staticmethod
    def _parse_alertmanager_v2(raw: list[dict[str, object]]) -> list[AlertInfo]:
        alerts = []
        for a in raw:
            labels: dict[str, str] = {
                str(k): str(v) for k, v in (a.get("labels") or {}).items()
            }
            annotations: dict[str, str] = {
                str(k): str(v) for k, v in (a.get("annotations") or {}).items()
            }
            status = a.get("status") or {}
            state = "firing" if (status.get("state") == "active") else "pending"
            alerts.append(
                AlertInfo(
                    name=labels.get("alertname", "Unknown"),
                    severity=labels.get("severity", "unknown").lower(),
                    state=state,
                    summary=annotations.get("summary", annotations.get("message", "")),
                    labels=labels,
                    started_at=str(a.get("startsAt") or ""),
                )
            )
        return alerts

    @staticmethod
    def _parse_legacy_alerts(raw: list[dict[str, object]]) -> list[AlertInfo]:
        alerts = []
        for a in raw:
            if a.get("state") not in ("alerting", "pending"):
                continue
            alerts.append(
                AlertInfo(
                    name=str(a.get("name", "Unknown")),
                    severity="unknown",
                    state="firing" if a.get("state") == "alerting" else "pending",
                    summary=str(a.get("message", "")),
                    labels={},
                    started_at=str(a.get("newStateDate") or ""),
                )
            )
        return alerts

    async def aclose(self) -> None:
        await self._http.aclose()


# ── FastAPI dependency ─────────────────────────────────────────────────────────

async def get_grafana_client(
    session_id: str,
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> GrafanaClient:
    """Dependency: resolves a session_id to a ready GrafanaClient.

    Raises 401 if the session is unknown (not yet connected).
    """
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail=(
                f"No active Grafana session for session_id='{session_id}'. "
                "Call POST /api/v1/grafana/connect first."
            ),
        )
    return await GrafanaClient.create(session)
