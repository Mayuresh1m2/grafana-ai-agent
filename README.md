# grafana-ai-agent

An AI-powered observability assistant that combines a local LLM (via Ollama) with your Grafana stack
(Loki, Prometheus, Tempo) to answer questions about metrics, logs, and traces in natural language.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            grafana-ai-agent                                  │
│                                                                              │
│   Browser                                                                    │
│  ┌──────────────────────┐                                                    │
│  │   Vue 3 SPA           │  :5173 (dev) / :80 (prod)                        │
│  │   Pinia · Vue Router  │                                                   │
│  └──────────┬───────────┘                                                    │
│             │ HTTP /api/v1                                                   │
│  ┌──────────▼───────────────────────────────────────────────┐               │
│  │               FastAPI Backend  :8000                      │               │
│  │  ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐ │               │
│  │  │ /health  │  │ /agent/query│  │  structlog  pydantic  │ │               │
│  │  └──────────┘  └──────┬──────┘  └──────────────────────┘ │               │
│  └─────────────────────┬─┴──────────────────────────────────┘               │
│                        │                                                     │
│          ┌─────────────┴──────────────────────┐                             │
│          │                                    │                             │
│  ┌───────▼────────┐              ┌────────────▼───────────────────────────┐ │
│  │ Ollama (host)  │              │   Observability Stack (Docker)         │ │
│  │  :11434        │              │                                        │ │
│  │  llama3 / etc  │              │  ┌──────────┐ ┌──────┐ ┌───────────┐  │ │
│  │  GPU / CPU     │              │  │ Grafana  │ │ Loki │ │Prometheus │  │ │
│  └────────────────┘              │  │  :3000   │ │:3100 │ │  :9090    │  │ │
│                                  │  └──────────┘ └──────┘ └───────────┘  │ │
│                                  │  ┌──────────┐ ┌──────────────────────┐ │ │
│                                  │  │  Tempo   │ │      Promtail        │ │ │
│                                  │  │  :3200   │ │  (log shipper)       │ │ │
│                                  │  └──────────┘ └──────────────────────┘ │ │
│                                  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘

  Deployment
  ┌──────────────────────────────────────────────────────────┐
  │  k3s / Kubernetes                                        │
  │  ┌─────────────────────┐   ┌──────────────────────────┐ │
  │  │  backend Deployment │   │  frontend Deployment     │ │
  │  │  replicas: 2        │   │  replicas: 2  (nginx)    │ │
  │  └─────────────────────┘   └──────────────────────────┘ │
  │  ┌──────────────────────────────────────────────────────┐│
  │  │  nginx Ingress  grafana-ai-agent.local               ││
  │  └──────────────────────────────────────────────────────┘│
  └──────────────────────────────────────────────────────────┘
```

## Repository layout

```
grafana-ai-agent/
├── backend/               Python 3.11 FastAPI service
│   ├── src/
│   │   ├── api/           Route handlers
│   │   ├── models/        Pydantic v2 request/response models
│   │   ├── services/      Ollama & Grafana HTTP clients
│   │   └── utils/         Structured logging helpers
│   └── tests/             pytest + pytest-asyncio test suite
├── frontend/              Vue 3 + TypeScript SPA
│   ├── src/
│   │   ├── api/           Typed Axios wrappers
│   │   ├── stores/        Pinia stores
│   │   ├── types/         Shared TypeScript interfaces
│   │   ├── router/        Vue Router 4 routes
│   │   ├── views/         Page-level components
│   │   └── components/    Reusable UI components
│   └── tests/             Vitest unit + Playwright e2e
├── k8s/                   Plain Kubernetes manifests
├── helm/                  Helm chart (grafana-ai-agent)
├── scripts/               Local dev helper scripts + config files
│   ├── grafana/           Grafana provisioning
│   ├── prometheus/        Prometheus config
│   ├── tempo/             Tempo config
│   └── promtail/          Promtail config
└── docs/                  Architecture and ADRs
```

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | |
| [uv](https://docs.astral.sh/uv/) | latest | replaces pip/venv |
| Node.js | 20 LTS | |
| npm | 10+ | |
| Docker + Compose | 24+ | observability stack |
| [Ollama](https://ollama.com) | latest | runs **on host** |
| kubectl | 1.29+ | optional, for k8s deploy |
| k3s | latest | optional, local k8s |

## Quick start

```bash
# 1. Clone and enter the repo
git clone https://github.com/your-org/grafana-ai-agent.git
cd grafana-ai-agent

# 2. Run the automated setup checker
chmod +x scripts/setup-local.sh
./scripts/setup-local.sh          # verifies Ollama, GPU, k3s, creates .env files
# ./scripts/setup-local.sh --install-k3s  # also installs k3s

# 3. Install all dependencies
make install

# 4. Start dev environment (Docker stack + backend + frontend)
make dev
```

Services after `make dev`:

| Service | URL |
|---------|-----|
| Frontend (Vue SPA) | http://localhost:5173 |
| Backend (FastAPI) | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Grafana | http://localhost:3000 (admin/admin) |
| Prometheus | http://localhost:9090 |
| Loki | http://localhost:3100 |
| Tempo | http://localhost:3200 |

## Development

```bash
make install          # Install backend (uv) + frontend (npm) deps
make dev              # Start full local stack
make test             # Run backend pytest + frontend vitest
make lint             # ruff + mypy + eslint + tsc
make format           # ruff format + prettier
make build            # Build backend wheel + frontend static assets
make docker-build     # Build both Docker images
make down             # Stop Docker stack
```

### Backend only

```bash
cd backend
uv sync --all-extras
uv run uvicorn src.main:app --reload
uv run pytest -v
uv run ruff check src/ tests/
uv run mypy src/
```

### Frontend only

```bash
cd frontend
npm ci
npm run dev
npm run test:unit
npm run test:e2e     # requires dev server running
npm run lint
npm run type-check
```

## Environment variables

Copy `backend/.env.example` to `backend/.env` and adjust values:

```bash
cp backend/.env.example backend/.env
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama host URL |
| `OLLAMA_MODEL` | `llama3` | Default LLM model |
| `GRAFANA_BASE_URL` | `http://localhost:3000` | Grafana instance |
| `GRAFANA_API_KEY` | *(empty)* | Service account token |
| `DEBUG` | `false` | Enable debug logging |

## Kubernetes deployment

```bash
# Plain manifests
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/backend/
kubectl apply -f k8s/frontend/
kubectl apply -f k8s/ingress.yaml

# Helm
helm upgrade --install grafana-ai-agent ./helm \
  --namespace grafana-ai-agent \
  --create-namespace \
  --values helm/values.yaml
```

Add to `/etc/hosts` for local testing:
```
127.0.0.1  grafana-ai-agent.local
```

## CI

GitHub Actions runs lint + tests on every pull request. See
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

Coverage reports are uploaded to Codecov.

## Architecture notes

See [`docs/architecture.md`](docs/architecture.md) for component diagrams,
data-flow walkthroughs, and ADRs.
