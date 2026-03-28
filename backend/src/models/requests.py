"""Inbound request models."""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class AgentQueryRequest(BaseModel):
    """Request body for POST /api/v1/agent/query."""

    session_id: str | None = Field(
        default=None,
        description="Grafana session ID from the connect flow. Required for Grafana tool calls.",
    )
    query: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        description="Natural-language question for the AI agent.",
        examples=["What is the p99 latency of the checkout service over the last hour?"],
    )
    context: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional key-value context injected into the system prompt. "
            "E.g. {'dashboard': 'checkout', 'environment': 'production'}."
        ),
    )
    model: str | None = Field(
        default=None,
        description="Ollama model name. Falls back to OLLAMA_MODEL env var when null.",
        examples=["llama3", "mistral", "phi3"],
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0 = deterministic, 2 = very random).",
    )
    max_tokens: int = Field(
        default=2048,
        ge=1,
        le=8192,
        description="Maximum number of tokens in the response.",
    )


class GrafanaConnectRequest(BaseModel):
    """Request body for POST /api/v1/grafana/connect.

    Supports two authentication modes:
    - **Credentials** (username + password): uses headless Playwright login.
    - **Cookie relay** (cookie_header): user completes SSO manually in their
      browser (e.g. Microsoft login) and pastes the raw Cookie header value.
      The backend validates it immediately against /api/datasources.

    Exactly one mode must be supplied.
    """

    session_id: str = Field(
        ...,
        description="Opaque client-generated session identifier.",
    )
    grafana_url: str = Field(
        ...,
        description="Base URL of the Grafana instance (no trailing slash).",
        examples=["https://grafana.example.com"],
    )
    # ── Credentials mode ──────────────────────────────────────────────────────
    username: str | None = Field(default=None, description="Grafana username or e-mail.")
    password: str | None = Field(default=None, description="Grafana password.")
    # ── Cookie-relay mode ─────────────────────────────────────────────────────
    cookie_header: str | None = Field(
        default=None,
        description=(
            "Raw Cookie header value copied from the browser after completing "
            "SSO manually (e.g. 'grafana_session=abc123; grafana_session_expiry=...')."
        ),
    )
    # ── Service account token mode ────────────────────────────────────────────
    service_token: str | None = Field(
        default=None,
        description=(
            "Grafana service account token (starts with 'glsa_' on Grafana ≥ 9). "
            "Sent as 'Authorization: Bearer <token>' on every request."
        ),
        examples=["glsa_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    )
    # ── Azure CLI mode ────────────────────────────────────────────────────────
    azure_scope: str | None = Field(
        default=None,
        description=(
            "Azure AD scope for the Grafana application. "
            "Format: 'api://<grafana-app-client-id>/.default'. "
            "Requires 'az login' to be completed on the local machine. "
            "The backend fetches and auto-refreshes the token via AzureCliCredential."
        ),
        examples=["api://00000000-0000-0000-0000-000000000000/.default"],
    )


class GrafanaSsoBrowserRequest(BaseModel):
    """Request body for POST /api/v1/grafana/reauth.

    Opens a headed Chromium window so the user can complete SSO without
    manually copying cookies.  Works for both the initial connect flow and
    re-authentication after a session expires.
    """

    session_id: str = Field(..., description="Existing or new session identifier.")
    grafana_url: str | None = Field(
        default=None,
        description=(
            "Grafana base URL.  Required when creating a new session; "
            "inferred from the stored session when refreshing an existing one."
        ),
        examples=["https://grafana.example.com"],
    )


class GrafanaRefreshRequest(BaseModel):
    """Request body for POST /api/v1/grafana/refresh."""

    session_id: str = Field(..., description="Existing session to refresh.")
    cookie_header: str = Field(
        ...,
        description="Fresh Cookie header value obtained after re-logging in.",
    )


class ConversationTurn(BaseModel):
    """A single message turn for the report generator."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content (markdown for assistant).")


class ReportRequest(BaseModel):
    """Request body for POST /api/v1/agent/report."""

    conversation: list[ConversationTurn] = Field(
        ...,
        description="Full Q&A transcript from the investigation session.",
    )
    context: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Session context injected into the report prompt "
            "(namespace, environment, services, active_alerts, …)."
        ),
    )
    model: str | None = Field(
        default=None,
        description="Ollama model name. Falls back to OLLAMA_MODEL env var.",
    )
