"""Application configuration via pydantic-settings.

All values can be overridden through environment variables or a .env file.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "grafana-ai-agent"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # ── Ollama ───────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_timeout: float = Field(default=120.0, gt=0)

    # ── LLM provider ─────────────────────────────────────────────────────────
    llm_provider: str = "ollama"          # "ollama" | "anthropic"

    # ── Anthropic ────────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(default="", repr=False)
    anthropic_model: str = "claude-opus-4-6"

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key:   str = Field(default="", repr=False)
    openai_model:     str = "gpt-4o"
    openai_base_url:  str = ""   # Override for Azure OpenAI or compatible endpoints

    # ── Grafana ──────────────────────────────────────────────────────────────
    grafana_base_url: str = "http://localhost:3000"
    grafana_api_key: str = Field(default="", repr=False)

    # ── Loki ─────────────────────────────────────────────────────────────────
    loki_base_url: str = "http://localhost:3100"

    # ── Prometheus ───────────────────────────────────────────────────────────
    prometheus_base_url: str = "http://localhost:9090"

    # ── Tempo ────────────────────────────────────────────────────────────────
    tempo_base_url: str = "http://localhost:3200"

    # ── RAG / Embeddings ─────────────────────────────────────────────────────
    embedding_model:       str = "nomic-embed-text"
    embedding_vector_size: int = Field(default=768, gt=0,
                                       description="Dimension of embedding vectors (768 for nomic-embed-text).")

    # ── Qdrant (vector store for examples) ───────────────────────────────────
    qdrant_url:             str = "http://localhost:6333"
    qdrant_collection:      str = "query_examples"

    # ── SQLite (structured store for entities) ────────────────────────────────
    sqlite_db_path: str = "./data/grafana_ai.db"

    # ── Service graph (topology map) ──────────────────────────────────────────
    # Override to a path inside your project repo so the graph can be committed.
    service_graph_path: str = "./data/service_graph.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (singleton)."""
    return Settings()
