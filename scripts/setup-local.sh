#!/usr/bin/env bash
# setup-local.sh — verify prerequisites and prepare the local dev environment
# Usage:
#   ./scripts/setup-local.sh              — check everything
#   ./scripts/setup-local.sh --install-k3s — also install k3s if missing
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
log_step()  { echo -e "\n${BOLD}── $* ──${NC}"; }

INSTALL_K3S="${1:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Grafana AI Agent — Local Setup     ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

# ── 1. Ollama ─────────────────────────────────────────────────────────────────
log_step "Checking Ollama"
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    MODELS=$(curl -sf http://localhost:11434/api/tags | python3 -c \
        "import sys,json; d=json.load(sys.stdin); print(', '.join(m['name'] for m in d.get('models',[])) or 'none')" 2>/dev/null || echo "unknown")
    log_ok "Ollama is running on :11434  (models: ${MODELS})"
else
    log_error "Ollama is NOT running.\n\n  Start it with:  ollama serve\n  Install from:   https://ollama.com"
fi

# ── 2. GPU detection ─────────────────────────────────────────────────────────
log_step "GPU Detection"
if command -v nvidia-smi &>/dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || echo "unknown")
    log_ok "NVIDIA GPU: ${GPU_INFO}"
    export OLLAMA_GPU=nvidia
elif command -v rocm-smi &>/dev/null; then
    log_ok "AMD ROCm GPU detected"
    export OLLAMA_GPU=rocm
elif [[ "$(uname -s)" == "Darwin" ]] && system_profiler SPDisplaysDataType 2>/dev/null | grep -q "Metal"; then
    METAL_GPU=$(system_profiler SPDisplaysDataType 2>/dev/null | awk '/Chipset Model/{print $NF}' | head -1)
    log_ok "Apple Silicon / Metal GPU: ${METAL_GPU}"
    export OLLAMA_GPU=metal
else
    log_warn "No GPU detected — Ollama will run on CPU (inference will be slower)"
    export OLLAMA_GPU=cpu
fi

# ── 3. Required tools ─────────────────────────────────────────────────────────
log_step "Required Tools"
REQUIRED_TOOLS=(docker node npm python3)
OPTIONAL_TOOLS=(uv kubectl k3s helm)

for tool in "${REQUIRED_TOOLS[@]}"; do
    if command -v "${tool}" &>/dev/null; then
        VER=$("${tool}" --version 2>/dev/null | head -1 | sed 's/^[^0-9]*//')
        log_ok "${tool}  ${VER}"
    else
        log_error "Required tool not found: ${tool}"
    fi
done

for tool in "${OPTIONAL_TOOLS[@]}"; do
    if command -v "${tool}" &>/dev/null; then
        VER=$("${tool}" --version 2>/dev/null | head -1 | sed 's/^[^0-9]*//')
        log_ok "${tool}  ${VER}"
    else
        log_warn "Optional tool not found: ${tool}"
    fi
done

# Verify Docker daemon is accessible
if ! docker info &>/dev/null 2>&1; then
    log_error "Docker daemon is not running. Start Docker Desktop or 'sudo systemctl start docker'."
fi

# ── 4. k3s / kubectl ─────────────────────────────────────────────────────────
log_step "Kubernetes (k3s)"
if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null 2>&1; then
    CTX=$(kubectl config current-context 2>/dev/null || echo "unknown")
    log_ok "kubectl connected  (context: ${CTX})"
elif command -v k3s &>/dev/null; then
    log_ok "k3s binary found (run 'sudo k3s server &' to start)"
elif [[ "${INSTALL_K3S}" == "--install-k3s" ]]; then
    log_info "Installing k3s..."
    curl -sfL https://get.k3s.io | sh -
    mkdir -p "${HOME}/.kube"
    sudo k3s kubectl config view --raw > "${HOME}/.kube/config"
    chmod 600 "${HOME}/.kube/config"
    log_ok "k3s installed successfully"
else
    log_warn "k3s not found. Run './scripts/setup-local.sh --install-k3s' to install."
fi

# ── 5. Environment files ──────────────────────────────────────────────────────
log_step "Environment Files"
BACKEND_ENV="${REPO_ROOT}/backend/.env"
FRONTEND_ENV="${REPO_ROOT}/frontend/.env"

if [[ ! -f "${BACKEND_ENV}" ]]; then
    cp "${REPO_ROOT}/backend/.env.example" "${BACKEND_ENV}"
    log_ok "Created ${BACKEND_ENV}"
else
    log_ok "${BACKEND_ENV} already exists"
fi

if [[ ! -f "${FRONTEND_ENV}" ]]; then
    echo "VITE_API_BASE_URL=/api/v1" > "${FRONTEND_ENV}"
    log_ok "Created ${FRONTEND_ENV}"
else
    log_ok "${FRONTEND_ENV} already exists"
fi

# ── 6. Pull Ollama model ──────────────────────────────────────────────────────
log_step "Ollama Model"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3}"

if curl -sf http://localhost:11434/api/tags | grep -q "\"${OLLAMA_MODEL}\"" 2>/dev/null; then
    log_ok "Model '${OLLAMA_MODEL}' is already available"
else
    log_info "Pulling model '${OLLAMA_MODEL}'…  (this may take several minutes)"
    ollama pull "${OLLAMA_MODEL}"
    log_ok "Model '${OLLAMA_MODEL}' pulled successfully"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Setup complete! Next steps:        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""
echo "  make install   — install all dependencies"
echo "  make dev       — start docker stack + backend + frontend"
echo "  make test      — run all tests"
echo "  make lint      — run all linters"
echo ""
