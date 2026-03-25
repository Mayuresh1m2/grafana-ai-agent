"""Browser-based authentication against a Grafana instance.

Uses Playwright (headless Chromium) to navigate to the login page,
fill in credentials, and extract the session cookie for subsequent
API calls via the Grafana datasource proxy.
"""

from __future__ import annotations

import httpx
import structlog
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

logger = structlog.get_logger(__name__)

_LOGIN_TIMEOUT_MS = 30_000  # 30 s to reach + log in
_NAV_TIMEOUT_MS = 10_000


class GrafanaAuthError(Exception):
    """Raised when browser-based Grafana authentication fails."""


class GrafanaAuthService:
    """Authenticates against a Grafana instance via headless Chromium.

    Typical flow
    ────────────
    1. Navigate to ``grafana_url`` (may redirect to /login).
    2. Fill username + password in the login form.
    3. Submit and wait for navigation away from /login.
    4. Extract all cookies from the browser context.
    5. Use those cookies for subsequent httpx calls to the Grafana REST API.
    """

    async def authenticate(
        self,
        grafana_url: str,
        username: str,
        password: str,
    ) -> dict[str, str]:
        """Log in via headless browser and return all response cookies.

        Args:
            grafana_url: Base URL of the Grafana instance (no trailing slash).
            username: Grafana username or e-mail.
            password: Grafana password.

        Returns:
            Dict mapping cookie name → value (e.g. ``{"grafana_session": "..."}``).

        Raises:
            GrafanaAuthError: If the login page is unreachable, credentials are
                wrong, or the browser times out.
        """
        log = logger.bind(grafana_url=grafana_url, username=username)
        log.info("grafana_auth_start")

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(headless=True)
            try:
                context: BrowserContext = await browser.new_context(
                    ignore_https_errors=True,   # handle self-signed TLS certs
                )
                page: Page = await context.new_page()

                # ── Navigate ──────────────────────────────────────────────────
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

                # ── Login form ────────────────────────────────────────────────
                if "/login" in page.url:
                    log.debug("grafana_login_page_detected")
                    await self._fill_login_form(page, username, password)

                    # Wait until we leave the /login page
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

                # ── Extract cookies ───────────────────────────────────────────
                raw_cookies = await context.cookies()
                cookies = {c["name"]: c["value"] for c in raw_cookies}
                log.info("grafana_auth_success", cookie_count=len(cookies))
                return cookies

            finally:
                await browser.close()

    async def fetch_datasources(
        self,
        grafana_url: str,
        cookies: dict[str, str],
    ) -> list[dict[str, object]]:
        """Call ``GET /api/datasources`` using the authenticated session cookie.

        Args:
            grafana_url: Grafana base URL.
            cookies: Cookies extracted by :meth:`authenticate`.

        Returns:
            Raw list of datasource dicts from the Grafana API.
        """
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        async with httpx.AsyncClient(
            base_url=grafana_url,
            headers={"Cookie": cookie_header, "Accept": "application/json"},
            verify=False,  # noqa: S501 — same self-signed cert tolerance as browser
            timeout=15.0,
        ) as client:
            try:
                resp = await client.get("/api/datasources")
                resp.raise_for_status()
                result: list[dict[str, object]] = resp.json()
                logger.info("datasources_fetched", count=len(result))
                return result
            except httpx.HTTPStatusError as exc:
                raise GrafanaAuthError(
                    f"Grafana returned HTTP {exc.response.status_code} for /api/datasources"
                ) from exc
            except Exception as exc:
                raise GrafanaAuthError(f"Failed to fetch datasources: {exc}") from exc

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _fill_login_form(
        self, page: Page, username: str, password: str
    ) -> None:
        """Fill and submit the standard Grafana login form."""
        # Username — Grafana uses different placeholders across versions
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

        # Password
        try:
            await page.fill('input[type="password"]', password, timeout=5_000)
        except Exception as exc:
            raise GrafanaAuthError("Could not find the password field") from exc

        # Submit button
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
