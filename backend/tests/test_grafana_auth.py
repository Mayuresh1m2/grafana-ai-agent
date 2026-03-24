"""Tests for app/tools/grafana_auth.py.

Test categories
---------------
Unit tests (no external I/O, run in CI):
  * GrafanaToken model — property logic, Pydantic validation
  * TokenStore — Fernet encrypt/decrypt roundtrip, missing-key fallback, multi-URL
  * GrafanaAuthExtractor.validate_token — mocked httpx
  * GrafanaAuthExtractor.extract_token — mocked Playwright (cookie, bearer, localStorage paths)
  * GrafanaAuthExtractor.refresh_token — mocked Playwright
  * Error conditions — GrafanaAuthTimeout, GrafanaAuthFailed, GrafanaTokenExpired

Integration tests (require a live Grafana instance, skipped in CI):
  * Marked with @pytest.mark.integration
  * Run with: pytest -m integration
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from cryptography.fernet import Fernet

from app.tools.grafana_auth import (
    GrafanaAuthExtractor,
    GrafanaAuthFailed,
    GrafanaAuthTimeout,
    GrafanaToken,
    GrafanaTokenExpired,
    TokenStore,
    _build_http_auth,
    _extract_from_page,
    _get_cookies,
    _inject_status_bar,
    _restore_cookies,
    _update_status_bar_done,
)

# ── Helpers / shared fixtures ──────────────────────────────────────────────────

_GRAFANA_URL = "http://localhost:3000"
_NOW = datetime.now(tz=timezone.utc)


def _make_token(
    value: str = "test-session-xyz",
    token_type: str = "cookie",
    expiry: datetime | None = None,
    raw_cookies: dict[str, str] | None = None,
    grafana_url: str = _GRAFANA_URL,
) -> GrafanaToken:
    return GrafanaToken(
        value=value,
        token_type=token_type,  # type: ignore[arg-type]
        expiry=expiry,
        raw_cookies=raw_cookies or {"grafana_session": value},
        grafana_url=grafana_url,
    )


@pytest.fixture
def fernet_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set GRAFANA_TOKEN_KEY to a fresh key and return it."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("GRAFANA_TOKEN_KEY", key)
    return key


@pytest.fixture
def token_store(tmp_path: Path, fernet_env: str) -> TokenStore:
    """Return a TokenStore backed by a temp file with a known encryption key."""
    return TokenStore(path=tmp_path / "tokens.json")


# ── Playwright mock factory ────────────────────────────────────────────────────

def _make_pw_mocks(
    *,
    has_login_element: bool = True,
    cookies: list[dict[str, str]] | None = None,
    ls_value: str | None = None,
    document_cookie: str = "",
) -> tuple[MagicMock, AsyncMock, AsyncMock, AsyncMock]:
    """Build a complete Playwright mock hierarchy.

    Returns (mock_async_playwright, mock_page, mock_context, mock_browser).
    """
    _cookies = cookies if cookies is not None else [
        {"name": "grafana_session", "value": "sess-from-mock"},
    ]

    # page
    mock_page = AsyncMock()
    mock_page.on = MagicMock()  # synchronous event registration
    mock_page.goto = AsyncMock()

    # query_selector: return a truthy mock if the "user is logged in", else None
    login_el = MagicMock() if has_login_element else None
    mock_page.query_selector = AsyncMock(return_value=login_el)

    # evaluate: first call = ls_value, second call = document.cookie
    mock_page.evaluate = AsyncMock(side_effect=[ls_value, document_cookie])

    # context
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.cookies = AsyncMock(return_value=_cookies)
    mock_context.close = AsyncMock()
    mock_context.add_cookies = AsyncMock()

    # browser
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    # pw instance
    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    # async_playwright() context manager
    mock_async_pw = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_async_pw.return_value = mock_cm

    return mock_async_pw, mock_page, mock_context, mock_browser


# ══════════════════════════════════════════════════════════════════════════════
# GrafanaToken model
# ══════════════════════════════════════════════════════════════════════════════

class TestGrafanaToken:

    def test_smoke_module_imports(self) -> None:
        """Smoke: all public symbols are importable from app.tools."""
        from app.tools import (  # noqa: F401
            GrafanaAuthExtractor,
            GrafanaAuthFailed,
            GrafanaAuthTimeout,
            GrafanaToken,
            GrafanaTokenExpired,
            TokenStore,
        )

    def test_token_defaults(self) -> None:
        token = GrafanaToken(value="abc", token_type="cookie")
        assert token.expiry is None
        assert token.raw_cookies == {}
        assert token.grafana_url == ""
        assert token.captured_at is not None

    def test_is_expired_none_expiry(self) -> None:
        token = _make_token(expiry=None)
        assert token.is_expired is False

    def test_is_expired_future(self) -> None:
        token = _make_token(expiry=_NOW + timedelta(hours=1))
        assert token.is_expired is False

    def test_is_expired_past(self) -> None:
        token = _make_token(expiry=_NOW - timedelta(seconds=1))
        assert token.is_expired is True

    def test_needs_refresh_none_expiry(self) -> None:
        token = _make_token(expiry=None)
        assert token.needs_refresh is False

    def test_needs_refresh_far_future(self) -> None:
        token = _make_token(expiry=_NOW + timedelta(hours=2))
        assert token.needs_refresh is False

    def test_needs_refresh_within_margin(self) -> None:
        # Expires in 3 minutes — within the 5-minute refresh margin
        token = _make_token(expiry=_NOW + timedelta(minutes=3))
        assert token.needs_refresh is True

    def test_needs_refresh_already_expired(self) -> None:
        token = _make_token(expiry=_NOW - timedelta(minutes=1))
        assert token.needs_refresh is True

    def test_token_type_literal_validation(self) -> None:
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            GrafanaToken(value="x", token_type="session")  # type: ignore[arg-type]

    def test_bearer_token_roundtrip(self) -> None:
        token = GrafanaToken(
            value="eyJhbGciOiJSUzI1NiJ9.payload.sig",
            token_type="bearer",
            raw_cookies={"grafana_session": "also-here"},
        )
        assert token.value.startswith("eyJ")
        assert token.token_type == "bearer"

    def test_api_key_token(self) -> None:
        token = GrafanaToken(value="glsa_abc123", token_type="api_key")
        assert token.token_type == "api_key"

    def test_model_serialization(self) -> None:
        token = _make_token(expiry=_NOW + timedelta(hours=1))
        serialized = token.model_dump_json()
        restored = GrafanaToken.model_validate_json(serialized)
        assert restored.value == token.value
        assert restored.token_type == token.token_type
        assert restored.raw_cookies == token.raw_cookies


# ══════════════════════════════════════════════════════════════════════════════
# TokenStore
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenStore:

    def test_smoke(self, token_store: TokenStore) -> None:
        assert token_store is not None

    def test_load_missing_url_returns_none(self, token_store: TokenStore) -> None:
        assert token_store.load("http://not-stored:3000") is None

    def test_save_and_load_roundtrip(self, token_store: TokenStore) -> None:
        token = _make_token(value="secret-session", grafana_url=_GRAFANA_URL)
        token_store.save(token)
        loaded = token_store.load(_GRAFANA_URL)
        assert loaded is not None
        assert loaded.value == "secret-session"
        assert loaded.token_type == "cookie"
        assert loaded.raw_cookies == token.raw_cookies

    def test_stored_file_is_encrypted(self, token_store: TokenStore, tmp_path: Path) -> None:
        token = _make_token(value="super-secret")
        token_store.save(token)
        raw = (tmp_path / "tokens.json").read_text()
        # The plaintext value must NOT appear in the ciphertext file
        assert "super-secret" not in raw

    def test_multiple_urls_stored_independently(self, token_store: TokenStore) -> None:
        t1 = _make_token(value="token-a", grafana_url="http://grafana-a:3000")
        t2 = _make_token(value="token-b", grafana_url="http://grafana-b:3000")
        token_store.save(t1)
        token_store.save(t2)
        assert token_store.load("http://grafana-a:3000") is not None
        assert token_store.load("http://grafana-b:3000") is not None
        assert token_store.load("http://grafana-a:3000").value == "token-a"  # type: ignore[union-attr]
        assert token_store.load("http://grafana-b:3000").value == "token-b"  # type: ignore[union-attr]

    def test_overwrite_same_url(self, token_store: TokenStore) -> None:
        token_store.save(_make_token(value="first"))
        token_store.save(_make_token(value="second"))
        loaded = token_store.load(_GRAFANA_URL)
        assert loaded is not None
        assert loaded.value == "second"

    def test_delete_removes_entry(self, token_store: TokenStore) -> None:
        token_store.save(_make_token())
        token_store.delete(_GRAFANA_URL)
        assert token_store.load(_GRAFANA_URL) is None

    def test_delete_missing_url_is_noop(self, token_store: TokenStore) -> None:
        token_store.delete("http://never-saved:3000")  # should not raise

    def test_wrong_fernet_key_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key_a = Fernet.generate_key().decode()
        key_b = Fernet.generate_key().decode()

        monkeypatch.setenv("GRAFANA_TOKEN_KEY", key_a)
        store_a = TokenStore(path=tmp_path / "tokens.json")
        store_a.save(_make_token(value="written-with-key-a"))

        monkeypatch.setenv("GRAFANA_TOKEN_KEY", key_b)
        store_b = TokenStore(path=tmp_path / "tokens.json")
        # Loading with the wrong key must return None gracefully
        assert store_b.load(_GRAFANA_URL) is None

    def test_missing_key_generates_fernet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GRAFANA_TOKEN_KEY", raising=False)
        store = TokenStore(path=tmp_path / "tokens.json")
        # Must still work for the duration of the process
        store.save(_make_token(value="ephemeral"))
        assert store.load(_GRAFANA_URL) is not None

    def test_corrupted_file_returns_none(
        self, tmp_path: Path, fernet_env: str
    ) -> None:
        path = tmp_path / "tokens.json"
        path.write_text('{"http://localhost:3000": "not-valid-fernet"}')
        store = TokenStore(path=path)
        assert store.load(_GRAFANA_URL) is None

    def test_expiry_preserved_across_roundtrip(self, token_store: TokenStore) -> None:
        expiry = _NOW + timedelta(hours=8)
        token = _make_token(expiry=expiry)
        token_store.save(token)
        loaded = token_store.load(_GRAFANA_URL)
        assert loaded is not None
        # Serialised datetime may lose sub-second precision; compare to the second
        assert abs((loaded.expiry - expiry).total_seconds()) < 1  # type: ignore[operator]


# ══════════════════════════════════════════════════════════════════════════════
# _build_http_auth helper
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildHttpAuth:

    def test_bearer_goes_into_headers(self) -> None:
        token = _make_token(value="my-bearer", token_type="bearer")
        headers, cookies = _build_http_auth(token)
        assert headers["Authorization"] == "Bearer my-bearer"
        assert cookies == {}

    def test_api_key_goes_into_headers(self) -> None:
        token = _make_token(value="glsa_xyz", token_type="api_key")
        headers, cookies = _build_http_auth(token)
        assert headers["Authorization"] == "Bearer glsa_xyz"
        assert cookies == {}

    def test_cookie_goes_into_cookies(self) -> None:
        raw = {"grafana_session": "sess-val", "csrf_token": "csrf-val"}
        token = _make_token(value="sess-val", token_type="cookie", raw_cookies=raw)
        headers, cookies = _build_http_auth(token)
        assert headers == {}
        assert cookies == raw


# ══════════════════════════════════════════════════════════════════════════════
# Free-function helpers (_extract_from_page, _get_cookies, etc.)
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractFromPage:

    @pytest.fixture
    def page_and_context(self) -> tuple[AsyncMock, AsyncMock]:
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])
        return mock_page, mock_context

    async def test_bearer_takes_priority(
        self, page_and_context: tuple[AsyncMock, AsyncMock]
    ) -> None:
        page, context = page_and_context
        context.cookies = AsyncMock(return_value=[
            {"name": "grafana_session", "value": "also-present"},
        ])
        token = await _extract_from_page(page, context, captured_bearer="intercept-bearer")
        assert token.token_type == "bearer"
        assert token.value == "intercept-bearer"
        # Raw cookies still captured for refresh
        assert "grafana_session" in token.raw_cookies

    async def test_grafana_session_cookie(
        self, page_and_context: tuple[AsyncMock, AsyncMock]
    ) -> None:
        page, context = page_and_context
        context.cookies = AsyncMock(return_value=[
            {"name": "grafana_session", "value": "cookie-token"},
        ])
        token = await _extract_from_page(page, context, captured_bearer=None)
        assert token.token_type == "cookie"
        assert token.value == "cookie-token"

    async def test_grafana_sess_alias(
        self, page_and_context: tuple[AsyncMock, AsyncMock]
    ) -> None:
        page, context = page_and_context
        context.cookies = AsyncMock(return_value=[
            {"name": "grafana_sess", "value": "short-cookie"},
        ])
        token = await _extract_from_page(page, context, captured_bearer=None)
        assert token.value == "short-cookie"

    async def test_localstorage_fallback(
        self, page_and_context: tuple[AsyncMock, AsyncMock]
    ) -> None:
        page, context = page_and_context
        # No cookies; first evaluate() = ls value, second = document.cookie
        page.evaluate = AsyncMock(side_effect=["ls-session-value", ""])
        token = await _extract_from_page(page, context, captured_bearer=None)
        assert token.value == "ls-session-value"
        assert token.token_type == "cookie"

    async def test_document_cookie_fallback(
        self, page_and_context: tuple[AsyncMock, AsyncMock]
    ) -> None:
        page, context = page_and_context
        # No cookies, no localStorage, but document.cookie has a session pair
        page.evaluate = AsyncMock(side_effect=[None, "grafana_session=doc-cookie-val"])
        token = await _extract_from_page(page, context, captured_bearer=None)
        assert token.value == "doc-cookie-val"

    async def test_raises_when_no_token_found(
        self, page_and_context: tuple[AsyncMock, AsyncMock]
    ) -> None:
        page, context = page_and_context
        page.evaluate = AsyncMock(side_effect=[None, ""])
        with pytest.raises(GrafanaAuthFailed, match="Could not extract"):
            await _extract_from_page(page, context, captured_bearer=None)


# ══════════════════════════════════════════════════════════════════════════════
# GrafanaAuthExtractor.validate_token (mocked httpx)
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateToken:

    async def test_smoke(self) -> None:
        extractor = GrafanaAuthExtractor(_GRAFANA_URL)
        assert extractor is not None

    async def test_valid_token_returns_true(self) -> None:
        token = _make_token(token_type="bearer", value="valid-bearer")
        extractor = GrafanaAuthExtractor(_GRAFANA_URL)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("app.tools.grafana_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await extractor.validate_token(token)

        assert result is True
        mock_client.get.assert_called_once_with(
            f"{_GRAFANA_URL}/api/user",
            headers={"Authorization": "Bearer valid-bearer"},
            cookies={},
        )

    async def test_expired_token_returns_false(self) -> None:
        token = _make_token(token_type="bearer", value="expired")
        extractor = GrafanaAuthExtractor(_GRAFANA_URL)

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch("app.tools.grafana_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await extractor.validate_token(token)

        assert result is False

    async def test_network_error_returns_false(self) -> None:
        token = _make_token(token_type="cookie")
        extractor = GrafanaAuthExtractor(_GRAFANA_URL)

        import httpx as _httpx

        with patch("app.tools.grafana_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(
                side_effect=_httpx.ConnectError("connection refused")
            )
            mock_client_cls.return_value = mock_client

            result = await extractor.validate_token(token)

        assert result is False

    async def test_cookie_token_sends_cookies(self) -> None:
        raw = {"grafana_session": "sess", "csrf_token": "csrf"}
        token = _make_token(token_type="cookie", raw_cookies=raw)
        extractor = GrafanaAuthExtractor(_GRAFANA_URL)

        mock_resp = MagicMock(status_code=200)

        with patch("app.tools.grafana_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await extractor.validate_token(token)

        _, kwargs = mock_client.get.call_args
        assert kwargs["cookies"] == raw
        assert kwargs["headers"] == {}

    async def test_custom_grafana_url_override(self) -> None:
        token = _make_token(token_type="bearer", value="tok")
        extractor = GrafanaAuthExtractor(_GRAFANA_URL)

        other_url = "http://other-grafana:3000"
        mock_resp = MagicMock(status_code=200)

        with patch("app.tools.grafana_auth.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await extractor.validate_token(token, grafana_url=other_url)

        call_args = mock_client.get.call_args
        assert call_args.args[0].startswith(other_url)


# ══════════════════════════════════════════════════════════════════════════════
# GrafanaAuthExtractor.extract_token (mocked Playwright)
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractToken:

    async def test_extract_token_cookie_path(
        self,
        token_store: TokenStore,
    ) -> None:
        """Happy path: grafana_session cookie is captured and persisted."""
        mock_async_pw, mock_page, mock_context, _ = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "grafana_session", "value": "happy-cookie"}],
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL,
            headless=True,
            store=token_store,
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            token = await extractor.extract_token()

        assert token.value == "happy-cookie"
        assert token.token_type == "cookie"
        assert token.grafana_url == _GRAFANA_URL
        # Verify persisted
        stored = token_store.load(_GRAFANA_URL)
        assert stored is not None
        assert stored.value == "happy-cookie"

    async def test_extract_token_bearer_path(
        self,
        token_store: TokenStore,
    ) -> None:
        """Bearer token captured from intercepted network request takes priority."""
        mock_async_pw, mock_page, mock_context, _ = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "grafana_session", "value": "also-present"}],
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL,
            headless=True,
            store=token_store,
        )

        def _fake_on(event: str, handler: object) -> None:
            # Immediately "fire" the request event so the bearer is captured
            if event == "request":
                fake_req = MagicMock()
                fake_req.headers = {"authorization": "Bearer intercept-bearer-tok"}
                fake_req.url = f"{_GRAFANA_URL}/api/ds/query"
                handler(fake_req)  # type: ignore[operator]

        mock_page.on = MagicMock(side_effect=_fake_on)

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            token = await extractor.extract_token()

        assert token.token_type == "bearer"
        assert token.value == "intercept-bearer-tok"

    async def test_extract_token_localstorage_path(
        self,
        token_store: TokenStore,
    ) -> None:
        """Fall through to localStorage when no cookies contain a session."""
        mock_async_pw, mock_page, mock_context, _ = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "irrelevant_cookie", "value": "x"}],
            ls_value="ls-grafana-session-token",
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL,
            headless=True,
            store=token_store,
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            token = await extractor.extract_token()

        assert token.value == "ls-grafana-session-token"
        assert token.token_type == "cookie"

    async def test_extract_token_injects_status_bar_when_not_headless(
        self,
        token_store: TokenStore,
    ) -> None:
        mock_async_pw, mock_page, mock_context, _ = _make_pw_mocks(
            cookies=[{"name": "grafana_session", "value": "s"}],
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL,
            headless=False,       # show browser = inject overlay
            store=token_store,
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock), \
             patch("app.tools.grafana_auth._inject_status_bar", new_callable=AsyncMock) as mock_inject, \
             patch("app.tools.grafana_auth._update_status_bar_done", new_callable=AsyncMock) as mock_done:

            await extractor.extract_token()

        mock_inject.assert_called_once()
        mock_done.assert_called_once()

    async def test_extract_token_skips_status_bar_when_headless(
        self,
        token_store: TokenStore,
    ) -> None:
        mock_async_pw, _, _, _ = _make_pw_mocks(
            cookies=[{"name": "grafana_session", "value": "s"}],
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL,
            headless=True,
            store=token_store,
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock), \
             patch("app.tools.grafana_auth._inject_status_bar", new_callable=AsyncMock) as mock_inject, \
             patch("app.tools.grafana_auth._update_status_bar_done", new_callable=AsyncMock) as mock_done:

            await extractor.extract_token()

        mock_inject.assert_not_called()
        mock_done.assert_not_called()

    async def test_browser_closed_on_success(self, token_store: TokenStore) -> None:
        mock_async_pw, _, mock_context, mock_browser = _make_pw_mocks(
            cookies=[{"name": "grafana_session", "value": "s"}],
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            await extractor.extract_token()

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()

    async def test_browser_closed_on_timeout(self, token_store: TokenStore) -> None:
        """Browser is properly closed even when a timeout exception is raised."""
        mock_async_pw, mock_page, mock_context, mock_browser = _make_pw_mocks(
            has_login_element=False,  # never logged in
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, timeout=0.01, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            with pytest.raises(GrafanaAuthTimeout):
                await extractor.extract_token()

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# GrafanaAuthExtractor.refresh_token (mocked Playwright)
# ══════════════════════════════════════════════════════════════════════════════

class TestRefreshToken:

    async def test_refresh_success(self, token_store: TokenStore) -> None:
        """Happy path: stored cookies produce a valid session."""
        mock_async_pw, mock_page, mock_context, _ = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "grafana_session", "value": "refreshed-session"}],
        )
        stale_token = _make_token(
            value="old-session",
            raw_cookies={"grafana_session": "old-session"},
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            fresh = await extractor.refresh_token(stale_token)

        assert fresh.value == "refreshed-session"
        assert fresh.grafana_url == _GRAFANA_URL
        # Cookies were restored
        mock_context.add_cookies.assert_called_once()

    async def test_refresh_restores_cookies_before_navigation(
        self, token_store: TokenStore
    ) -> None:
        """Cookies must be set before page.goto so Grafana sees the session."""
        call_order: list[str] = []

        mock_async_pw, mock_page, mock_context, _ = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "grafana_session", "value": "s"}],
        )

        original_add = mock_context.add_cookies
        original_goto = mock_page.goto

        async def _tracking_add_cookies(*args: object, **kwargs: object) -> None:
            call_order.append("add_cookies")
            return await original_add(*args, **kwargs)

        async def _tracking_goto(*args: object, **kwargs: object) -> None:
            call_order.append("goto")
            return await original_goto(*args, **kwargs)

        mock_context.add_cookies = _tracking_add_cookies
        mock_page.goto = _tracking_goto

        stale = _make_token(raw_cookies={"grafana_session": "old"})
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            await extractor.refresh_token(stale)

        assert call_order.index("add_cookies") < call_order.index("goto")

    async def test_refresh_no_cookies_raises_token_expired(
        self, token_store: TokenStore
    ) -> None:
        token = _make_token(raw_cookies={})
        extractor = GrafanaAuthExtractor(_GRAFANA_URL, store=token_store)

        with pytest.raises(GrafanaTokenExpired, match="no cookies"):
            await extractor.refresh_token(token)

    async def test_refresh_failed_login_raises_token_expired(
        self, token_store: TokenStore
    ) -> None:
        """When Grafana doesn't recognise the stored cookies, raise GrafanaTokenExpired."""
        mock_async_pw, _, _, _ = _make_pw_mocks(
            has_login_element=False,  # cookie rejected — not logged in
        )
        token = _make_token(raw_cookies={"grafana_session": "expired-cookie"})
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            with pytest.raises(GrafanaTokenExpired, match="Cookie refresh failed"):
                await extractor.refresh_token(token)

    async def test_browser_closed_after_refresh(self, token_store: TokenStore) -> None:
        mock_async_pw, _, mock_context, mock_browser = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "grafana_session", "value": "s"}],
        )
        token = _make_token(raw_cookies={"grafana_session": "old"})
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            await extractor.refresh_token(token)

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()

    async def test_refresh_uses_headless_regardless_of_extractor_setting(
        self, token_store: TokenStore
    ) -> None:
        """refresh_token must always launch headless, ignoring self.headless."""
        mock_async_pw, _, _, mock_browser = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "grafana_session", "value": "s"}],
        )
        # Extractor configured for non-headless (user-facing) mode
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=False, store=token_store
        )
        token = _make_token(raw_cookies={"grafana_session": "old"})

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            await extractor.refresh_token(token)

        launch_kwargs = mock_browser.__class__.new_context.call_args
        # Access the pw.chromium.launch call
        pw_mock = mock_async_pw.return_value.__aenter__.return_value
        launch_call = pw_mock.chromium.launch.call_args
        assert launch_call.kwargs.get("headless", launch_call.args[0] if launch_call.args else None) is True


# ══════════════════════════════════════════════════════════════════════════════
# Error condition unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorConditions:

    async def test_auth_timeout_raised_after_poll_expires(
        self, token_store: TokenStore
    ) -> None:
        mock_async_pw, mock_page, _, _ = _make_pw_mocks(has_login_element=False)
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, timeout=0.01, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            with pytest.raises(GrafanaAuthTimeout) as exc_info:
                await extractor.extract_token()

        assert _GRAFANA_URL in str(exc_info.value)

    async def test_auth_timeout_message_contains_seconds(
        self, token_store: TokenStore
    ) -> None:
        mock_async_pw, _, _, _ = _make_pw_mocks(has_login_element=False)
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, timeout=42, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            with pytest.raises(GrafanaAuthTimeout, match="42"):
                await extractor.extract_token()

    async def test_auth_failed_raised_when_page_has_no_token(
        self, token_store: TokenStore
    ) -> None:
        mock_async_pw, mock_page, mock_context, _ = _make_pw_mocks(
            has_login_element=True,
            cookies=[{"name": "unrelated", "value": "x"}],
            ls_value=None,
            document_cookie="",  # nothing session/token shaped
        )
        extractor = GrafanaAuthExtractor(
            _GRAFANA_URL, headless=True, store=token_store
        )

        with patch("app.tools.grafana_auth.async_playwright", mock_async_pw), \
             patch("app.tools.grafana_auth.asyncio.sleep", new_callable=AsyncMock):

            with pytest.raises(GrafanaAuthFailed, match="Could not extract"):
                await extractor.extract_token()

    async def test_token_expired_raised_when_no_cookies_for_refresh(
        self,
    ) -> None:
        extractor = GrafanaAuthExtractor(_GRAFANA_URL)
        empty_token = _make_token(raw_cookies={})
        with pytest.raises(GrafanaTokenExpired):
            await extractor.refresh_token(empty_token)

    def test_exception_hierarchy(self) -> None:
        assert issubclass(GrafanaAuthTimeout, GrafanaAuthError)
        assert issubclass(GrafanaAuthFailed, GrafanaAuthError)
        assert issubclass(GrafanaTokenExpired, GrafanaAuthError)


# ══════════════════════════════════════════════════════════════════════════════
# Status bar injection helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestStatusBarHelpers:

    async def test_inject_status_bar_calls_evaluate(self) -> None:
        mock_page = AsyncMock()
        await _inject_status_bar(mock_page)
        mock_page.evaluate.assert_called_once()
        js_arg = mock_page.evaluate.call_args.args[0]
        assert "gaia-status-bar" in js_arg
        assert "waiting for your login" in js_arg

    async def test_inject_status_bar_grafana_message(self) -> None:
        mock_page = AsyncMock()
        await _inject_status_bar(mock_page)
        js = mock_page.evaluate.call_args.args[0]
        assert "Close browser only after you see the Grafana dashboard" in js

    async def test_inject_status_bar_does_not_raise_on_evaluate_error(self) -> None:
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("page closed"))
        await _inject_status_bar(mock_page)  # must not propagate

    async def test_update_status_bar_done_calls_evaluate(self) -> None:
        mock_page = AsyncMock()
        await _update_status_bar_done(mock_page)
        mock_page.evaluate.assert_called_once()
        js_arg = mock_page.evaluate.call_args.args[0]
        assert "Login detected" in js_arg

    async def test_update_status_bar_done_does_not_raise_on_error(self) -> None:
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("context destroyed"))
        await _update_status_bar_done(mock_page)  # must not propagate


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests (require live Grafana, skipped in CI)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestGrafanaAuthIntegration:
    """End-to-end tests that need a real Grafana instance.

    Run with:
        pytest -m integration --grafana-url http://localhost:3000
    """

    @pytest.fixture(autouse=True)
    def require_grafana_url(self, request: pytest.FixtureRequest) -> None:
        url = request.config.getoption("--grafana-url", default=None)
        if not url:
            pytest.skip("Pass --grafana-url to run integration tests")

    async def test_validate_token_against_live_grafana(
        self, request: pytest.FixtureRequest
    ) -> None:
        """A real API key or session cookie must pass /api/user validation."""
        url: str = request.config.getoption("--grafana-url")
        api_key: str = os.environ.get("GRAFANA_API_KEY", "")
        if not api_key:
            pytest.skip("Set GRAFANA_API_KEY env var for this test")

        token = GrafanaToken(
            value=api_key,
            token_type="api_key",
            grafana_url=url,
        )
        extractor = GrafanaAuthExtractor(url)
        valid = await extractor.validate_token(token, grafana_url=url)
        assert valid is True

    async def test_extract_token_opens_browser_and_waits(
        self, request: pytest.FixtureRequest, tmp_path: Path, fernet_env: str
    ) -> None:
        """Full interactive extraction — requires a human to log in."""
        url: str = request.config.getoption("--grafana-url")
        store = TokenStore(path=tmp_path / "tokens.json")
        extractor = GrafanaAuthExtractor(url, headless=False, store=store)

        token = await extractor.extract_token()

        assert token.value
        assert token.token_type in ("cookie", "bearer", "api_key")
        assert token.grafana_url == url
        assert store.load(url) is not None


# ── pytest CLI option for integration tests ────────────────────────────────────

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--grafana-url",
        action="store",
        default=None,
        help="Base URL of a live Grafana instance for integration tests",
    )
