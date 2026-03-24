#!/usr/bin/env bash
# get-host-ip.sh — Print the host machine's IP as seen from inside a k8s pod.
#
# Usage:
#   OLLAMA_BASE_URL=$(./scripts/get-host-ip.sh):11434
#
# Detection order:
#   1. k3d  — host.k3d.internal (resolved via /etc/hosts inside k3d nodes)
#   2. kind — host.docker.internal (Docker Desktop on macOS/Windows)
#   3. bare metal / k3s / kubeadm — default gateway of eth0
#
# Exit codes:
#   0 — host IP printed to stdout
#   1 — could not determine the host IP

set -euo pipefail

# ── 1. k3d ────────────────────────────────────────────────────────────────────
if getent hosts host.k3d.internal &>/dev/null; then
    echo "host.k3d.internal"
    exit 0
fi

# ── 2. Docker Desktop (kind, colima, Rancher Desktop) ────────────────────────
if getent hosts host.docker.internal &>/dev/null; then
    echo "host.docker.internal"
    exit 0
fi

# ── 3. Default gateway (bare metal / kubeadm / k3s) ──────────────────────────
# Works inside a Linux pod: the host is typically the default gateway.
GW=$(ip route show default 2>/dev/null | awk '/default via/ {print $3; exit}')
if [[ -n "${GW}" ]]; then
    echo "${GW}"
    exit 0
fi

# ── Fallback ──────────────────────────────────────────────────────────────────
echo "Could not determine host IP. Set OLLAMA_BASE_URL explicitly." >&2
exit 1
