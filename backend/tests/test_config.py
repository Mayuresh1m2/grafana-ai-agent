"""Tests for src.config."""

from __future__ import annotations

import pytest

from src.config import Settings, get_settings


def test_config_module_smoke() -> None:
    """Smoke: config module imports correctly."""
    from src import config

    assert hasattr(config, "Settings")
    assert hasattr(config, "get_settings")


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "grafana-ai-agent"
    assert settings.port == 8000
    assert settings.ollama_model == "llama3"
    assert settings.debug is False
    assert settings.log_level == "INFO"


def test_settings_cors_origins_include_vite() -> None:
    settings = Settings()
    assert "http://localhost:5173" in settings.cors_origins


def test_settings_cors_origins_include_grafana() -> None:
    settings = Settings()
    assert "http://localhost:3000" in settings.cors_origins


def test_get_settings_returns_settings_instance() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)


def test_get_settings_is_cached() -> None:
    a = get_settings()
    b = get_settings()
    assert a is b


def test_settings_ollama_timeout_positive() -> None:
    settings = Settings()
    assert settings.ollama_timeout > 0


def test_settings_port_override() -> None:
    settings = Settings(port=9000)
    assert settings.port == 9000


def test_settings_grafana_api_key_default_empty() -> None:
    settings = Settings()
    assert settings.grafana_api_key == ""
