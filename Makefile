.DEFAULT_GOAL := help
.PHONY: install install-backend install-frontend \
        dev dev-backend dev-frontend \
        test test-backend test-frontend test-e2e \
        lint lint-backend lint-frontend \
        format format-backend format-frontend \
        build build-backend build-frontend \
        docker-build docker-build-backend docker-build-frontend \
        helm-lint helm-template-test \
        pre-commit-install clean down help

BACKEND_DIR  := backend
FRONTEND_DIR := frontend
HELM_CHART   := helm/grafana-ai-agent

DOCKER_REGISTRY ?= ghcr.io/mayuresh1m2
VERSION        ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")
BUILD_DATE     := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
GIT_COMMIT     ?= $(shell git rev-parse HEAD 2>/dev/null || echo "unknown")

# ── Colours ───────────────────────────────────────────────────────────────────
CYAN  := \033[0;36m
RESET := \033[0m

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'

# ── Install ───────────────────────────────────────────────────────────────────
install: install-backend install-frontend ## Install all dependencies

install-backend: ## Install backend deps with uv
	cd $(BACKEND_DIR) && uv sync --all-extras

install-frontend: ## Install frontend deps with npm
	cd $(FRONTEND_DIR) && npm ci

# ── Dev ───────────────────────────────────────────────────────────────────────
dev: ## Start Docker stack, backend, and frontend concurrently
	docker compose -f docker-compose.dev.yml up -d
	@echo ""
	@echo "  Grafana    -> http://localhost:3000  (admin/admin)"
	@echo "  Prometheus -> http://localhost:9090"
	@echo "  Loki       -> http://localhost:3100"
	@echo "  Tempo      -> http://localhost:3200"
	@echo ""
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## Start FastAPI dev server (hot-reload)
	cd $(BACKEND_DIR) && uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Start Vite dev server
	cd $(FRONTEND_DIR) && npm run dev

down: ## Stop the Docker observability stack
	docker compose -f docker-compose.dev.yml down

# ── Test ──────────────────────────────────────────────────────────────────────
test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend pytest suite
	cd $(BACKEND_DIR) && uv run pytest -v --tb=short

test-frontend: ## Run frontend Vitest unit tests
	cd $(FRONTEND_DIR) && npm run test:unit

test-e2e: ## Run Playwright e2e tests (requires dev server)
	cd $(FRONTEND_DIR) && npm run test:e2e

# ── Lint ──────────────────────────────────────────────────────────────────────
lint: lint-backend lint-frontend ## Lint all code

lint-backend: ## ruff check + mypy
	cd $(BACKEND_DIR) && uv run ruff check src/ tests/
	cd $(BACKEND_DIR) && uv run ruff format --check src/ tests/
	cd $(BACKEND_DIR) && uv run mypy src/

lint-frontend: ## eslint + prettier check + tsc
	cd $(FRONTEND_DIR) && npm run lint
	cd $(FRONTEND_DIR) && npm run format:check
	cd $(FRONTEND_DIR) && npm run type-check

# ── Format ────────────────────────────────────────────────────────────────────
format: format-backend format-frontend ## Auto-format all code

format-backend: ## ruff format
	cd $(BACKEND_DIR) && uv run ruff format src/ tests/
	cd $(BACKEND_DIR) && uv run ruff check --fix src/ tests/

format-frontend: ## prettier + eslint --fix
	cd $(FRONTEND_DIR) && npm run format
	cd $(FRONTEND_DIR) && npm run lint:fix

# ── Build ─────────────────────────────────────────────────────────────────────
build: build-backend build-frontend ## Build all artefacts

build-backend: ## Build backend wheel
	cd $(BACKEND_DIR) && uv build

build-frontend: ## Build frontend static assets
	cd $(FRONTEND_DIR) && npm run build

# ── Docker ────────────────────────────────────────────────────────────────────
docker-build: docker-build-backend docker-build-frontend ## Build both Docker images

docker-build-backend: ## Build backend image (passes APP_VERSION, BUILD_DATE, GIT_COMMIT)
	docker build \
		--build-arg APP_VERSION=$(VERSION) \
		--build-arg BUILD_DATE=$(BUILD_DATE) \
		--build-arg GIT_COMMIT=$(GIT_COMMIT) \
		--tag $(DOCKER_REGISTRY)/grafana-ai-agent-backend:$(VERSION) \
		--tag $(DOCKER_REGISTRY)/grafana-ai-agent-backend:latest \
		--file $(BACKEND_DIR)/Dockerfile \
		$(BACKEND_DIR)

docker-build-frontend: ## Build frontend image
	docker build \
		--tag $(DOCKER_REGISTRY)/grafana-ai-agent-frontend:$(VERSION) \
		--tag $(DOCKER_REGISTRY)/grafana-ai-agent-frontend:latest \
		--file $(FRONTEND_DIR)/Dockerfile \
		$(FRONTEND_DIR)

# ── Helm ──────────────────────────────────────────────────────────────────────
HELM_TEST_ARGS := \
	--set ollama.hostUrl=http://host.k3d.internal:11434 \
	--set secrets.grafanaTokenKey=ci-test-token

helm-lint: ## Lint the Helm chart
	helm lint $(HELM_CHART) $(HELM_TEST_ARGS)

helm-template-test: ## Render chart and validate with kubectl dry-run (no cluster needed)
	helm template grafana-ai-agent $(HELM_CHART) $(HELM_TEST_ARGS) \
		| kubectl apply --dry-run=client -f -

# ── Misc ──────────────────────────────────────────────────────────────────────
pre-commit-install: ## Install git pre-commit hooks (backend)
	cd $(BACKEND_DIR) && uv run pre-commit install

clean: ## Remove build artefacts and caches
	cd $(BACKEND_DIR) && rm -rf dist/ .mypy_cache/ .ruff_cache/ .pytest_cache/ htmlcov/ .coverage coverage.xml
	cd $(FRONTEND_DIR) && rm -rf dist/ node_modules/.cache/ coverage/ playwright-report/ test-results/
