"""Tests for GET /api/v1/health/."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


def test_health_module_smoke() -> None:
    """Smoke: health module imports and router exists."""
    from src.api.health import router

    assert router is not None


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/api/v1/health/")
    assert response.status_code == 200


def test_health_returns_ok_status(client: TestClient) -> None:
    data = client.get("/api/v1/health/").json()
    assert data["status"] == "ok"


def test_health_returns_version(client: TestClient) -> None:
    data = client.get("/api/v1/health/").json()
    assert "version" in data
    assert data["version"]


def test_readiness_returns_200(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200


def test_readiness_returns_ok(client: TestClient) -> None:
    data = client.get("/api/v1/health/ready").json()
    assert data["status"] == "ok"


def test_health_response_schema(client: TestClient) -> None:
    data = client.get("/api/v1/health/").json()
    assert set(data.keys()) == {"status", "version"}
