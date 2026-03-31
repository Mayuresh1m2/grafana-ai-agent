"""Browser-based authentication against a Grafana instance.

Two strategies are supported:

* **Headless credentials** (:meth:`GrafanaAuthService.authenticate`) — fills the
  standard Grafana login form in a non-visible browser and returns the resulting
  session cookies.  Suitable for username/password accounts.

* **Headed SSO** (:meth:`GrafanaAuthService.reauth_sso`) — opens a visible browser
  window, waits for the user to complete Microsoft (or any other) SSO, then
  captures all cookies automatically.  No DevTools copy-paste required.

Both methods return a ``dict[cookie_name, cookie_value]`` that can be stored in
:class:`~src.services.session_store.GrafanaSession` and forwarded as a ``Cookie``
request header to the Grafana API.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

logger = structlog.get_logger(__name__)

_LOGIN_TIMEOUT_MS = 30_000   # 30 s to navigate + submit credentials
_SSO_TIMEOUT_MS   = 180_000  # 3 min for the user to complete SSO

# Persistent browser profiles are stored here, one sub-directory per Grafana URL.
# Each profile retains cookies, localStorage, and session state so users are not
# forced to re-login after the backend restarts or after browser windows close.
_PROFILE_BASE = Path("./data/playwright-profiles")


def _profile_dir(grafana_url: str) -> Path:
    """Return (and create) a profile directory specific to *grafana_url*."""
    slug = re.sub(r"[^\w]", "_", grafana_url.lower()).strip("_")[:60]
    path = _PROFILE_BASE / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


class GrafanaAuthError(Exception):
    """Raised when browser-based Grafana authentication fails."""


# ── Shared browser infrastructure ─────────────────────────────────────────────

@asynccontextmanager
async def _browser_page(
    grafana_url: str,
    *,
    headless: bool,
) -> AsyncIterator[tuple[BrowserContext, Page]]:
    """Launch a persistent-profile browser, navigate to *grafana_url*, and
    yield ``(context, page)``.

    Using ``launch_persistent_context`` saves cookies and browser storage to
    disk, so users only have to log in once per Grafana instance regardless of
    backend restarts or tool reloads.
    """
    profile = _profile_dir(grafana_url)
    async with async_playwright() as pw:
        context: BrowserContext = await pw.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            ignore_https_errors=True,   # tolerate self-signed TLS certs
        )
        try:
            page: Page = await context.new_page()
            try:
                await page.goto(
                    grafana_url,
                    wait_until="networkidle",
                    timeout=_LOGIN_TIMEOUT_MS,
                )
            except PlaywrightTimeout as exc:
                raise GrafanaAuthError(
                    f"Timed out reaching {grafana_url} — is the URL correct?"
                ) from exc
            except Exception as exc:
                raise GrafanaAuthError(
                    f"Could not reach {grafana_url}: {exc}"
                ) from exc
            yield context, page
        finally:
            await context.close()


# ── Auth service ──────────────────────────────────────────────────────────────

class GrafanaAuthService:
    """Browser-based Grafana authentication (credentials and SSO)."""

    async def authenticate(
        self,
        grafana_url: str,
        username: str,
        password: str,
    ) -> dict[str, str]:
        """Log in via headless browser and return all session cookies.

        Args:
            grafana_url: Base URL of the Grafana instance (no trailing slash).
            username: Grafana username or e-mail.
            password: Grafana password.

        Returns:
            Dict mapping cookie name → value.

        Raises:
            GrafanaAuthError: If the login page is unreachable, credentials are
                wrong, or the browser times out.
        """
        log = logger.bind(grafana_url=grafana_url, username=username)
        log.info("grafana_auth_start")

        async with _browser_page(grafana_url, headless=True) as (context, page):
            if "/login" in page.url:
                log.debug("grafana_login_page_detected")
                await self._fill_login_form(page, username, password)
                try:
                    await page.wait_for_url(
                        lambda url: "/login" not in url,
                        timeout=_LOGIN_TIMEOUT_MS,
                    )
                except PlaywrightTimeout:
                    error_msg = await self._read_login_error(page)
                    raise GrafanaAuthError(
                        f"Login failed — {error_msg or 'check username and password'}"
                    )

            cookies = {c["name"]: c["value"] for c in await context.cookies()}
            log.info("grafana_auth_success", cookie_count=len(cookies))
            return cookies

    async def reauth_sso(self, grafana_url: str) -> dict[str, str]:
        """Open a visible browser window and wait for the user to complete SSO.

        Opens Grafana in a headed browser without filling any forms.  Once the
        user finishes SSO and lands on the Grafana dashboard, all cookies
        (including ``HttpOnly``) are captured and returned automatically.

        Args:
            grafana_url: Base URL of the Grafana instance.

        Returns:
            Dict mapping cookie name → value.

        Raises:
            GrafanaAuthError: If the browser cannot reach Grafana, the user
                closes the window, or login is not completed within 3 minutes.
        """
        log = logger.bind(grafana_url=grafana_url)
        log.info("grafana_sso_browser_start")

        async with _browser_page(grafana_url, headless=False) as (context, page):
            if "/login" not in page.url and page.url.startswith(grafana_url):
                log.info("grafana_sso_already_authenticated")
            else:
                try:
                    await page.wait_for_url(
                        lambda url: url.startswith(grafana_url) and "/login" not in url,
                        timeout=_SSO_TIMEOUT_MS,
                    )
                except PlaywrightTimeout as exc:
                    raise GrafanaAuthError(
                        "SSO login timed out — please complete login within 3 minutes."
                    ) from exc
                except Exception as exc:
                    raise GrafanaAuthError(
                        f"Browser closed before SSO completed: {exc}"
                    ) from exc

            cookies = {c["name"]: c["value"] for c in await context.cookies()}
            log.info("grafana_sso_browser_success", cookie_count=len(cookies))
            return cookies

    # ── Private helpers (credentials login only) ──────────────────────────────

    async def _fill_login_form(
        self, page: Page, username: str, password: str
    ) -> None:
        """Fill and submit the standard Grafana login form."""
        username_selectors = [
            'input[name="user"]',
            'input[placeholder*="username" i]',
            'input[placeholder*="email" i]',
            'input[autocomplete="username"]',
        ]
        filled = False
        for sel in username_selectors:
            try:
                await page.fill(sel, username, timeout=2_000)
                filled = True
                break
            except Exception:
                continue
        if not filled:
            raise GrafanaAuthError(
                "Could not find the username field on the Grafana login page"
            )

        try:
            await page.fill('input[type="password"]', password, timeout=5_000)
        except Exception as exc:
            raise GrafanaAuthError("Could not find the password field") from exc

        submit_selectors = [
            'button[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Sign in")',
            'button:has-text("Login")',
            'input[type="submit"]',
        ]
        clicked = False
        for sel in submit_selectors:
            try:
                await page.click(sel, timeout=2_000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise GrafanaAuthError("Could not find the submit button on the login page")

    async def _read_login_error(self, page: Page) -> str:
        """Try to extract the error message Grafana shows after a failed login."""
        error_selectors = [
            '[data-testid="data-testid Alert error"]',
            ".alert-error",
            ".login-error-message",
            '[class*="alert"][class*="error"]',
        ]
        for sel in error_selectors:
            try:
                text = await page.locator(sel).first.text_content(timeout=1_000)
                if text:
                    return text.strip()
            except Exception:
                continue
        return ""
