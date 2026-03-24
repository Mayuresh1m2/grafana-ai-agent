"""Smoke tests for service modules — verify imports and class structure."""

from __future__ import annotations


def test_ollama_service_module_smoke() -> None:
    """Smoke: OllamaService and factory import correctly."""
    from src.services.ollama import OllamaService, get_ollama_service

    assert OllamaService is not None
    assert callable(get_ollama_service)


def test_ollama_service_has_expected_methods() -> None:
    from src.services.ollama import OllamaService

    assert hasattr(OllamaService, "generate")
    assert hasattr(OllamaService, "list_models")
    assert hasattr(OllamaService, "aclose")


def test_grafana_service_module_smoke() -> None:
    """Smoke: GrafanaService imports correctly."""
    from src.services.grafana import GrafanaService, get_grafana_service

    assert GrafanaService is not None
    assert callable(get_grafana_service)


def test_grafana_service_has_expected_methods() -> None:
    from src.services.grafana import GrafanaService

    assert hasattr(GrafanaService, "get_datasources")
    assert hasattr(GrafanaService, "query_loki")
    assert hasattr(GrafanaService, "query_prometheus")
    assert hasattr(GrafanaService, "aclose")


def test_utils_logging_module_smoke() -> None:
    """Smoke: logging utils import and are callable."""
    from src.utils.logging import configure_logging

    assert callable(configure_logging)


def test_services_package_smoke() -> None:
    """Smoke: services __init__ exports expected symbols."""
    from src import services

    assert hasattr(services, "OllamaService")
    assert hasattr(services, "GrafanaService")
