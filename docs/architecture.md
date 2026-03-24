# Architecture

## Overview

`grafana-ai-agent` is a monorepo containing a Vue 3 SPA frontend, a Python FastAPI
backend, and supporting infrastructure configuration. The system lets users ask
natural-language questions about their Grafana observability stack using a locally
hosted LLM (Ollama).

## Component diagram

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  Browser                                                                │
  │  ┌────────────────────────────────────────┐                            │
  │  │  Vue 3 SPA  (port 5173 dev / 80 prod) │                            │
  │  │  ┌──────────┐  ┌───────────┐           │                            │
  │  │  │  Pinia   │  │Vue Router │           │                            │
  │  │  │  stores  │  │  4 routes │           │                            │
  │  │  └──────────┘  └───────────┘           │                            │
  │  │  ┌────────────────────────────────┐    │                            │
  │  │  │  Axios typed API client        │    │                            │
  │  │  │  /api/v1/*                     │    │                            │
  │  │  └─────────────┬──────────────────┘    │                            │
  │  └────────────────┼───────────────────────┘                            │
  │                   │ HTTP                                                │
  │  ┌────────────────▼───────────────────────────────────────────────┐    │
  │  │  FastAPI Backend  (port 8000)                                  │    │
  │  │                                                                │    │
  │  │  POST /api/v1/agent/query                                      │    │
  │  │    ├─ AgentQueryRequest  (Pydantic v2)                         │    │
  │  │    ├─ OllamaService.generate()                                 │    │
  │  │    └─ AgentQueryResponse (Pydantic v2)                         │    │
  │  │                                                                │    │
  │  │  GET  /api/v1/health/                                          │    │
  │  │  GET  /api/v1/health/ready                                     │    │
  │  │                                                                │    │
  │  │  structlog → JSON lines → Loki (via Promtail)                  │    │
  │  └────────┬─────────────────────────────────┬─────────────────────┘    │
  │           │                                 │                          │
  │           ▼                                 ▼                          │
  │  ┌─────────────────┐              ┌──────────────────────────────────┐ │
  │  │  Ollama (HOST)  │              │  Observability Docker stack      │ │
  │  │  port 11434     │              │                                  │ │
  │  │                 │              │  ┌──────────┐  ┌──────────────┐  │ │
  │  │  llama3         │              │  │ Grafana  │  │  Prometheus  │  │ │
  │  │  mistral        │              │  │  :3000   │  │    :9090     │  │ │
  │  │  phi3           │              │  └──────────┘  └──────────────┘  │ │
  │  │  …              │              │  ┌──────────┐  ┌──────────────┐  │ │
  │  │  GPU / CPU      │              │  │   Loki   │  │    Tempo     │  │ │
  │  └─────────────────┘              │  │  :3100   │  │    :3200     │  │ │
  │                                   │  └──────────┘  └──────────────┘  │ │
  │                                   │  ┌──────────────────────────────┐ │ │
  │                                   │  │  Promtail (log collector)    │ │ │
  │                                   │  └──────────────────────────────┘ │ │
  │                                   └──────────────────────────────────┘ │
  └─────────────────────────────────────────────────────────────────────────┘
```

## Data flow — agent query

```
User types question
        │
        ▼
  Vue ChatView.vue
  useAgentStore.sendQuery()
        │
        │  POST /api/v1/agent/query
        │  { "query": "...", "context": {...} }
        ▼
  FastAPI  src/api/agent.py
  AgentQueryRequest (validated by Pydantic v2)
        │
        ▼
  OllamaService.generate()
        │  POST http://host:11434/api/generate
        │  { "model": "llama3", "prompt": "...", "system": "..." }
        ▼
  Ollama (local LLM)
        │  {"response": "...", "eval_count": 128}
        ▼
  AgentQueryResponse
        │
        └──▶ Store answer in Pinia messages[]
             Render in AgentChat.vue
```

## Key design decisions

### ADR-001: Ollama runs on the host, not in Docker

**Decision:** Ollama is excluded from `docker-compose.dev.yml`.

**Rationale:** GPU passthrough to Docker containers is complex and fragile,
especially across NVIDIA, AMD, and Apple Silicon. Running Ollama natively allows
it to benefit from the host GPU/NPU directly. The backend reaches it via
`host.docker.internal:11434`.

### ADR-002: Pydantic v2 for all models

**Decision:** All request and response models use Pydantic v2 (`BaseModel`).

**Rationale:** v2 provides significant performance gains over v1, native Python
type annotation support, and better error messages. `pydantic-settings` is used
for environment configuration so all config is validated at startup.

### ADR-003: structlog for structured logging

**Decision:** All backend logging uses `structlog` with JSON output in production
and coloured console output in debug mode.

**Rationale:** JSON lines are natively ingested by Loki/Promtail without any
parsing pipeline. In debug mode the dev-friendly console renderer improves the
local development experience.

### ADR-004: Pinia composition-API stores

**Decision:** Pinia stores use the composition API (setup stores) rather than the
options API.

**Rationale:** Better TypeScript inference, smaller bundle, and consistency with
the rest of the Vue 3 codebase that uses `<script setup>` throughout.

### ADR-005: No `any` in TypeScript

**Decision:** `@typescript-eslint/no-explicit-any` is set to `error`.

**Rationale:** Removes an entire class of runtime errors. All API shapes are
modelled via interfaces in `src/types/`.

## Repository structure

```
grafana-ai-agent/
├── backend/
│   ├── src/
│   │   ├── api/          # FastAPI routers (health, agent)
│   │   ├── models/       # Pydantic v2 request/response schemas
│   │   ├── services/     # Ollama + Grafana async HTTP clients
│   │   └── utils/        # Structured logging helpers
│   └── tests/            # pytest + pytest-asyncio
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios typed wrappers
│   │   ├── stores/       # Pinia composition stores
│   │   ├── types/        # Shared TypeScript interfaces (no any)
│   │   ├── router/       # Vue Router 4 route definitions
│   │   ├── views/        # Page-level Vue components
│   │   └── components/   # Reusable UI components
│   └── tests/
│       ├── unit/         # Vitest unit tests
│       └── e2e/          # Playwright end-to-end tests
├── k8s/                  # Plain Kubernetes manifests
├── helm/                 # Helm chart (grafana-ai-agent)
├── scripts/              # Dev tooling + observability stack config
│   ├── grafana/          # Grafana provisioning (datasources, dashboards)
│   ├── prometheus/       # Prometheus scrape config
│   ├── tempo/            # Tempo tracing config
│   └── promtail/         # Promtail log collection config
└── docs/                 # Architecture docs and ADRs
```

## Infrastructure diagram (Kubernetes)

```
  Namespace: grafana-ai-agent
  ┌───────────────────────────────────────────────────────────────┐
  │                                                               │
  │  Ingress (nginx)  grafana-ai-agent.local                      │
  │    /api/*  ──▶  backend Service :80                           │
  │    /*      ──▶  frontend Service :80                          │
  │                                                               │
  │  ┌─────────────────────┐   ┌──────────────────────────────┐  │
  │  │  backend Deployment │   │  frontend Deployment         │  │
  │  │  replicas: 2        │   │  replicas: 2                 │  │
  │  │  FastAPI + uvicorn  │   │  nginx serving Vue SPA       │  │
  │  │  ConfigMap + Secret │   │                              │  │
  │  └─────────────────────┘   └──────────────────────────────┘  │
  │                                                               │
  │  HPA (optional):  backend 2–8  /  frontend 2–6               │
  │  PDB:  minAvailable=1 for both                                │
  │                                                               │
  └───────────────────────────────────────────────────────────────┘

  Note: Grafana stack (Prometheus, Loki, Tempo, Grafana) is deployed
  separately into the 'monitoring' namespace and is not part of this chart.
  Ollama runs on the node host and is reachable via host.docker.internal.
```
