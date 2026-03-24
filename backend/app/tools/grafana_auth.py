"""Playwright-based Grafana session token extractor with encrypted persistence.

Workflow
--------
1. Instantiate GrafanaAuthExtractor(grafana_url, headless=False).
2. Call await extractor.extract_token() — a real Chromium window opens, the user
   logs in, and a token is captured from network interception / cookies /
   localStorage, then persisted to disk with Fernet encryption.
3. On subsequent runs call extractor.refresh_token(token) to silently refresh
   the session using stored cookies (no user interaction required).
4. Call extractor.validate_token(token) at any time to verify liveness.

Token persistence
-----------------
Tokens are stored in ``backend/.secrets/grafana_tokens.json``.  Each entry is
Fernet-encrypted with the key in env var ``GRAFANA_TOKEN_KEY`` (URL-safe base64,
32 bytes).  If the variable is unset a fresh key is generated and printed as a
warning — set it in your .env to make tokens survive restarts.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
import structlog
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken as FernetInvalidToken
from playwright.async_api import (
    BrowserContext,
    Page,
    Request,
    async_playwright,
)
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# ── Tunables ───────────────────────────────────────────────────────────────────
_POLL_INTERVAL: float = 2.0          # seconds between login-check polls
_DEFAULT_TIMEOUT: float = 120.0      # seconds to wait for user login
_REFRESH_MARGIN: timedelta = timedelta(minutes=5)
_VALIDATE_TIMEOUT: float = 10.0      # seconds for /api/user validation call

# ── Paths ──────────────────────────────────────────────────────────────────────
# .secrets/ sits at the repo-level backend/ directory, outside source trees.
_SECRETS_DIR: Path = Path(__file__).parents[3] / ".secrets"
_TOKENS_FILE: Path = _SECRETS_DIR / "grafana_tokens.json"

# ── DOM selectors that indicate a completed Grafana login ─────────────────────
# Ordered from most-specific to least-specific so the first match wins.
_LOGGED_IN_SELECTORS: tuple[str, ...] = (
    '[data-testid="nav-menu-toggle"]',
    '[data-testid="data-testid Nav bar toggle menu button"]',
    'nav[aria-label="Main menu"]',
    '[aria-label="Open navigation menu"]',
    '.sidemenu',
    'a[aria-label="Home"]',
)

# ── Injected browser overlay ───────────────────────────────────────────────────
# Shown while the user is authenticating so they understand what the tool needs.
_STATUS_BAR_JS: str = r"""
() => {
    if (document.getElementById('gaia-status-bar')) return;
    const bar = document.createElement('div');
    bar.id = 'gaia-status-bar';
    bar.setAttribute('role', 'status');
    bar.style.cssText = [
        'position:fixed',
        'bottom:0',
        'left:0',
        'right:0',
        'z-index:2147483647',
        'background:#1f2937',
        'color:#f97316',
        'font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
        'font-size:13px',
        'font-weight:600',
        'padding:10px 20px',
        'text-align:center',
        'border-top:2px solid #f97316',
        'box-shadow:0 -4px 16px rgba(0,0,0,0.55)',
        'letter-spacing:0.015em',
        'line-height:1.5',
    ].join(';');
    bar.textContent = (
        'Grafana AI Agent \u2014 waiting for your login. '
        + 'Close browser only after you see the Grafana dashboard.'
    );
    document.body.appendChild(bar);
}
"""

_STATUS_BAR_DONE_JS: str = r"""
() => {
    const bar = document.getElementById('gaia-status-bar');
    if (!bar) return;
    bar.style.background = '#14532d';
    bar.style.borderTopColor = '#22c55e';
    bar.style.color = '#86efac';
    bar.textContent = (
        'Grafana AI Agent \u2014 Login detected! '
        + 'Token captured successfully. You may now close this window.'
    );
}
"""


# ── Exceptions ─────────────────────────────────────────────────────────────────

class GrafanaAuthError(Exception):
    """Base class for all Grafana authentication errors."""


class GrafanaAuthTimeout(GrafanaAuthError):
    """User did not complete login within the allotted timeout window."""


class GrafanaAuthFailed(GrafanaAuthError):
    """Token extraction or validation failed after a confirmed login."""


class GrafanaTokenExpired(GrafanaAuthError):
    """Stored token has expired and silent cookie-based refresh failed."""


# ── Data model ─────────────────────────────────────────────────────────────────

class GrafanaToken(BaseModel):
    """Captured Grafana authentication credential.

    ``token_type`` controls how the token is presented to Grafana:

    * ``"cookie"`` — ``grafana_session`` cookie (most common for local instances)
    * ``"bearer"`` — ``Authorization: Bearer <value>`` header (OAuth / OIDC)
    * ``"api_key"`` — Grafana service-account API key
    """

    value: str = Field(..., description="Primary token value")
    token_type: Literal["cookie", "bearer", "api_key"] = Field(
        ...,
        description="Presentation mechanism for this token",
    )
    expiry: datetime | None = Field(
        default=None,
        description="UTC expiry timestamp. None means unknown / non-expiring.",
    )
    raw_cookies: dict[str, str] = Field(
        default_factory=dict,
        description="Full cookie jar captured from the browser session.",
    )
    grafana_url: str = Field(
        default="",
        description="Origin Grafana instance URL (used as storage key).",
    )
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
        description="UTC timestamp when this token was first captured.",
    )

    # ── Computed properties ────────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        """Return True if the token has definitely passed its expiry time."""
        if self.expiry is None:
            return False
        return datetime.now(tz=timezone.utc) >= self.expiry

    @property
    def needs_refresh(self) -> bool:
        """Return True if the token expires within the refresh margin."""
        if self.expiry is None:
            return False
        return datetime.now(tz=timezone.utc) >= (self.expiry - _REFRESH_MARGIN)


# ── Encrypted token persistence ────────────────────────────────────────────────

class TokenStore:
    """Fernet-encrypted on-disk store for :class:`GrafanaToken` objects.

    The file is a plain JSON dict mapping ``grafana_url → encrypted_blob``.
    Each blob is individually encrypted so metadata such as the key (URL) is
    visible but the token value and cookies are not.
    """

    def __init__(self, path: Path = _TOKENS_FILE) -> None:
        self._path = path
        self._fernet = self._build_fernet()

    # ── Public API ─────────────────────────────────────────────────────────────

    def save(self, token: GrafanaToken) -> None:
        """Persist *token* to disk, overwriting any previous entry for its URL."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        store = self._read_raw()
        plaintext = token.model_dump_json().encode()
        store[token.grafana_url] = self._fernet.encrypt(plaintext).decode()

        self._path.write_text(json.dumps(store, indent=2))
        logger.debug("token_saved", grafana_url=token.grafana_url)

    def load(self, grafana_url: str) -> GrafanaToken | None:
        """Return the decrypted token for *grafana_url*, or None if not found."""
        store = self._read_raw()
        blob = store.get(grafana_url, "")
        if not blob:
            return None
        try:
            plaintext = self._fernet.decrypt(blob.encode())
            return GrafanaToken.model_validate_json(plaintext)
        except (FernetInvalidToken, Exception) as exc:
            logger.warning("token_load_failed", grafana_url=grafana_url, error=str(exc))
            return None

    def delete(self, grafana_url: str) -> None:
        """Remove the entry for *grafana_url* (no-op if absent)."""
        store = self._read_raw()
        if grafana_url in store:
            del store[grafana_url]
            self._path.write_text(json.dumps(store, indent=2))
            logger.debug("token_deleted", grafana_url=grafana_url)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _read_raw(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return dict(json.loads(self._path.read_text()))
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _build_fernet() -> Fernet:
        raw_key = os.environ.get("GRAFANA_TOKEN_KEY", "").strip()
        if raw_key:
            return Fernet(raw_key.encode())

        generated = Fernet.generate_key()
        logger.warning(
            "grafana_token_key_not_set",
            message=(
                "GRAFANA_TOKEN_KEY env var is missing. A temporary key has been "
                "generated for this session — tokens will NOT survive a restart. "
                "Add the key below to your .env file to enable persistence."
            ),
            generated_key=generated.decode(),
        )
        return Fernet(generated)


# ── Main extractor ─────────────────────────────────────────────────────────────

class GrafanaAuthExtractor:
    """Open a Playwright browser, capture a Grafana session token, persist it.

    Parameters
    ----------
    grafana_url:
        Base URL of the Grafana instance (e.g. ``http://localhost:3000``).
    headless:
        ``False`` (default) shows the browser window so the user can log in.
        ``True`` runs invisibly and is used for silent cookie-based refresh.
    timeout:
        Maximum seconds to wait for the user to complete login.
    store:
        Optional custom :class:`TokenStore` (useful for testing).
    """

    def __init__(
        self,
        grafana_url: str,
        headless: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
        store: TokenStore | None = None,
    ) -> None:
        self.grafana_url = grafana_url.rstrip("/")
        self.headless = headless
        self.timeout = timeout
        self._store: TokenStore = store or TokenStore()
        # Populated by the request interception callback (sync, set from async context)
        self._captured_bearer: str | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def extract_token(self) -> GrafanaToken:
        """Launch browser, wait for the user to log in, capture and return a token.

        The browser shows a persistent status overlay instructing the user not to
        close the window until they see the Grafana dashboard.

        Raises
        ------
        GrafanaAuthTimeout
            If the user does not complete login within *timeout* seconds.
        GrafanaAuthFailed
            If the page provides no usable token after a confirmed login.
        """
        log = logger.bind(grafana_url=self.grafana_url, headless=self.headless)
        log.info("grafana_auth_extract_start")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context()
            page = await context.new_page()

            self._captured_bearer = None
            page.on("request", self._on_request)

            try:
                await page.goto(self.grafana_url, wait_until="domcontentloaded")

                if not self.headless:
                    await _inject_status_bar(page)

                token = await self._wait_for_login(page, context)

                if not self.headless:
                    await _update_status_bar_done(page)
                    # Give the user a moment to see the success message
                    await asyncio.sleep(2)

            finally:
                await context.close()
                await browser.close()

        token.grafana_url = self.grafana_url
        self._store.save(token)
        log.info(
            "grafana_auth_token_captured",
            token_type=token.token_type,
            has_expiry=token.expiry is not None,
        )
        return token

    async def refresh_token(self, token: GrafanaToken) -> GrafanaToken:
        """Silently refresh *token* using its stored cookie jar.

        Launches a headless browser, restores the cookie session, confirms the
        session is still valid, then extracts a fresh token.

        Raises
        ------
        GrafanaTokenExpired
            If ``token.raw_cookies`` is empty or the cookies no longer produce
            an authenticated session.
        """
        log = logger.bind(grafana_url=self.grafana_url)
        log.info("grafana_auth_refresh_start")

        if not token.raw_cookies:
            raise GrafanaTokenExpired(
                "Cannot refresh: no cookies stored in token. "
                "Re-authenticate with extract_token()."
            )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()

            await _restore_cookies(context, self.grafana_url, token.raw_cookies)

            page = await context.new_page()
            self._captured_bearer = None
            page.on("request", self._on_request)

            try:
                await page.goto(self.grafana_url, wait_until="domcontentloaded")
                # Allow the page to process the restored session cookies
                await asyncio.sleep(3)

                if not await self._check_logged_in(page):
                    raise GrafanaTokenExpired(
                        "Cookie refresh failed — Grafana rejected the stored session. "
                        "Re-authenticate with extract_token()."
                    )

                fresh = await _extract_from_page(page, context, self._captured_bearer)

            finally:
                await context.close()
                await browser.close()

        fresh.grafana_url = self.grafana_url
        self._store.save(fresh)
        log.info("grafana_auth_refresh_done", token_type=fresh.token_type)
        return fresh

    async def validate_token(
        self,
        token: GrafanaToken,
        grafana_url: str | None = None,
    ) -> bool:
        """Return True if *token* is accepted by the Grafana ``/api/user`` endpoint.

        Uses a lightweight GET request; does not open a browser.
        """
        target = (grafana_url or self.grafana_url).rstrip("/")
        headers, cookies = _build_http_auth(token)
        log = logger.bind(grafana_url=target, token_type=token.token_type)
        log.debug("grafana_token_validate")

        try:
            async with httpx.AsyncClient(timeout=_VALIDATE_TIMEOUT) as client:
                resp = await client.get(
                    f"{target}/api/user",
                    headers=headers,
                    cookies=cookies,
                )
            valid = resp.status_code == 200
            log.info("grafana_token_validated", valid=valid, http_status=resp.status_code)
            return valid

        except httpx.HTTPError as exc:
            log.warning("grafana_token_validate_http_error", error=str(exc))
            return False

    # ── Request interception (sync callback) ───────────────────────────────────

    def _on_request(self, request: Request) -> None:
        """Capture the first Bearer token seen in outgoing request headers."""
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer ") and self._captured_bearer is None:
            self._captured_bearer = auth_header[len("bearer "):].strip()
            logger.debug(
                "bearer_token_intercepted",
                url=request.url,
                token_preview=self._captured_bearer[:8] + "…",
            )

    # ── Login polling ──────────────────────────────────────────────────────────

    async def _wait_for_login(
        self, page: Page, context: BrowserContext
    ) -> GrafanaToken:
        """Poll the page every *_POLL_INTERVAL* seconds until a login indicator
        appears, then extract and return the token.

        Raises GrafanaAuthTimeout if the deadline passes without success.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        log = logger.bind(timeout_s=self.timeout, poll_interval_s=_POLL_INTERVAL)
        log.info("waiting_for_user_login")

        while loop.time() < deadline:
            if await self._check_logged_in(page):
                log.info("login_confirmed")
                return await _extract_from_page(page, context, self._captured_bearer)
            await asyncio.sleep(_POLL_INTERVAL)

        raise GrafanaAuthTimeout(
            f"User did not complete Grafana login within {self.timeout:.0f} s. "
            f"URL: {self.grafana_url}"
        )

    async def _check_logged_in(self, page: Page) -> bool:
        """Return True when any post-login DOM selector is found on *page*."""
        for selector in _LOGGED_IN_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element is not None:
                    return True
            except Exception:
                # Playwright raises on closed pages / navigation; treat as not-logged-in
                continue
        return False


# ── Module-level helpers (free functions, easier to patch in tests) ────────────

async def _inject_status_bar(page: Page) -> None:
    """Inject the status-bar overlay into *page*; silently ignore failures."""
    try:
        await page.evaluate(_STATUS_BAR_JS)
    except Exception as exc:
        logger.debug("status_bar_inject_failed", error=str(exc))


async def _update_status_bar_done(page: Page) -> None:
    """Update the status bar to show the success state."""
    try:
        await page.evaluate(_STATUS_BAR_DONE_JS)
    except Exception as exc:
        logger.debug("status_bar_update_failed", error=str(exc))


async def _extract_from_page(
    page: Page,
    context: BrowserContext,
    captured_bearer: str | None,
) -> GrafanaToken:
    """Extract a GrafanaToken from the authenticated browser page.

    Priority order
    --------------
    1. Bearer token intercepted from outgoing network requests
    2. ``grafana_session`` cookie (or ``grafana_sess`` alias)
    3. ``grafana_session`` item from ``window.localStorage``
    4. Any cookie whose name contains "session" or "token" (document.cookie scan)

    Raises
    ------
    GrafanaAuthFailed
        When no token source yields a non-empty value.
    """
    raw_cookies = await _get_cookies(context)

    # 1. Bearer token from intercepted requests
    if captured_bearer:
        logger.debug("token_source_bearer")
        return GrafanaToken(
            value=captured_bearer,
            token_type="bearer",
            raw_cookies=raw_cookies,
        )

    # 2. grafana_session cookie
    session_value = raw_cookies.get("grafana_session") or raw_cookies.get("grafana_sess")
    if session_value:
        logger.debug("token_source_cookie")
        return GrafanaToken(
            value=session_value,
            token_type="cookie",
            raw_cookies=raw_cookies,
        )

    # 3. localStorage
    ls_value: str | None = await page.evaluate(
        "() => window.localStorage.getItem('grafana_session')"
    )
    if ls_value:
        logger.debug("token_source_localstorage")
        return GrafanaToken(
            value=str(ls_value),
            token_type="cookie",
            raw_cookies=raw_cookies,
        )

    # 4. Scan document.cookie for anything session/token-shaped
    raw_cookie_str: str = await page.evaluate("() => document.cookie") or ""
    for pair in raw_cookie_str.split(";"):
        name, _, val = pair.strip().partition("=")
        name_lower = name.lower()
        if ("session" in name_lower or "token" in name_lower) and val.strip():
            logger.debug("token_source_document_cookie", cookie_name=name.strip())
            return GrafanaToken(
                value=val.strip(),
                token_type="cookie",
                raw_cookies=raw_cookies,
            )

    raise GrafanaAuthFailed(
        "Could not extract a Grafana token from bearer interception, "
        "cookies, localStorage, or document.cookie after confirmed login."
    )


async def _get_cookies(context: BrowserContext) -> dict[str, str]:
    """Return the browser context's cookies as a plain ``name → value`` dict."""
    all_cookies = await context.cookies()
    return {c["name"]: c["value"] for c in all_cookies}


async def _restore_cookies(
    context: BrowserContext,
    grafana_url: str,
    raw_cookies: dict[str, str],
) -> None:
    """Load *raw_cookies* back into *context* so Grafana recognises the session."""
    parsed = urllib.parse.urlparse(grafana_url)
    domain = parsed.hostname or "localhost"
    await context.add_cookies(
        [
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "sameSite": "Lax",
            }
            for name, value in raw_cookies.items()
        ]
    )


def _build_http_auth(
    token: GrafanaToken,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(headers, cookies)`` for an httpx request against Grafana.

    * Bearer / API-key tokens go in the ``Authorization`` header.
    * Cookie-based tokens go in the cookies dict so httpx sets the Cookie header.
    """
    if token.token_type in ("bearer", "api_key"):
        return {"Authorization": f"Bearer {token.value}"}, {}
    return {}, dict(token.raw_cookies)
