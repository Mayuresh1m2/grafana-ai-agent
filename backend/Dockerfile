# syntax=docker/dockerfile:1.7
# ── Build arguments ────────────────────────────────────────────────────────────
ARG PYTHON_VERSION=3.11
ARG APP_VERSION=dev
ARG BUILD_DATE=unknown
ARG GIT_COMMIT=unknown

# ── Stage 1: dependency + browser builder ─────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /app

# uv — fast Python package manager (official distroless image)
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /usr/local/bin/uv

# Minimal system tools needed at build time
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps into an isolated .venv (layer-cached separately)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-editable

# Install Playwright Chromium + its system-level deps into a fixed path.
# The browser binaries are later copied into the runtime stage.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright
RUN uv run playwright install chromium --with-deps

# Copy application source last (invalidates cache only when code changes)
COPY src/ ./src/

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG APP_VERSION
ARG BUILD_DATE
ARG GIT_COMMIT

# OCI standard image labels
LABEL org.opencontainers.image.title="grafana-ai-agent-backend" \
      org.opencontainers.image.description="AI-powered Grafana observability assistant — FastAPI backend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.source="https://github.com/Mayuresh1m2/grafana-ai-agent" \
      org.opencontainers.image.licenses="MIT"

# curl for health check + Chromium shared-library runtime deps.
# playwright install-deps installs exactly the right packages for the
# distro/arch automatically; we run it here (as root) before switching users.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy venv first so playwright command is resolvable in the next RUN
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install only the Chromium *system* deps (not the browser — it comes from builder)
RUN playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — uid 1000 per spec
RUN addgroup --gid 1000 appgroup \
    && adduser  --uid 1000 --gid 1000 --no-create-home --disabled-password appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appgroup /app/.playwright /app/.playwright
COPY --from=builder --chown=appuser:appgroup /app/src         /app/src

ENV PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/app/.playwright \
    APP_VERSION="${APP_VERSION}"

USER appuser

EXPOSE 8000

# curl health check as specified
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:8000/api/v1/health/ || exit 1

# ENTRYPOINT (not CMD) — use CMD to override worker count in dev
ENTRYPOINT ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
