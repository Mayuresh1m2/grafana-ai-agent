"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.main import create_app


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Return a Settings object with overrides safe for testing."""
    return Settings(
        debug=True,
        log_level="DEBUG",
        ollama_base_url="http://localhost:11434",
        grafana_base_url="http://localhost:3000",
        grafana_api_key="",
    )


@pytest.fixture
def client() -> TestClient:
    """Return a synchronous TestClient wrapping the FastAPI app."""
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Fixture git repository (code_tools tests)
# ---------------------------------------------------------------------------

_SAMPLE_REPO_SRC = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a temporary git repo initialised from tests/fixtures/sample_repo/.

    The fixture:
    1. Copies the source files to a fresh temp directory.
    2. Runs ``git init`` + two commits to produce a realistic history.
    3. Returns the ``Path`` to the temp repo root.

    Session-scoped so git operations run only once per test session.
    """
    repo_dir: Path = tmp_path_factory.mktemp("sample_repo")
    shutil.copytree(_SAMPLE_REPO_SRC, repo_dir, dirs_exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
        )

    git("init")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test Runner")
    git("config", "commit.gpgsign", "false")

    # First commit — initial scaffold
    git("add", ".")
    git("commit", "-m", "Initial commit: microservice scaffold with known bugs")

    # Second commit — incomplete error handling (makes git log more realistic)
    config_path = repo_dir / "config.py"
    original = config_path.read_text()
    config_path.write_text(
        original + "\n# TODO: add error handling for missing keys\n"
    )
    git("add", "config.py")
    git("commit", "-m", "Add TODO for missing key error handling (incomplete)")

    return repo_dir
