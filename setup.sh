#!/usr/bin/env bash
#
# One-command setup for AskScotty teammates.
# Requires: Docker Desktop (running) and Node.js (for the mobile app).
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${BOLD}$*${NC}"; }
ok() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

info "AskScotty — setup"
echo

# --- Docker ---
if ! command -v docker >/dev/null 2>&1; then
  fail "Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker is installed but not running. Open Docker Desktop, wait until it says Running, then re-run ./setup.sh"
fi
ok "Docker is running"

if ! docker compose version >/dev/null 2>&1; then
  fail "Docker Compose is missing. Update Docker Desktop and try again."
fi
ok "Docker Compose is available"

# --- Env file ---
if [[ ! -f .env ]]; then
  cp .env.example .env
  ok "Created .env from .env.example"
else
  ok ".env already exists (leaving it alone)"
fi

# --- Backend + web via Docker ---
info "Building and starting database, API, and web app..."
docker compose up --build -d

info "Waiting for API health check..."
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${BACKEND_PORT:-8000}/api/health/" >/dev/null 2>&1; then
    ok "API is healthy at http://localhost:${BACKEND_PORT:-8000}/api/health/"
    break
  fi
  sleep 2
done

if ! curl -fsS "http://localhost:${BACKEND_PORT:-8000}/api/health/" >/dev/null 2>&1; then
  warn "API did not respond yet. Check logs with: docker compose logs -f backend"
fi

# --- Mobile (Expo runs on your machine, not in Docker) ---
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  ok "Node $(node -v) found"
  info "Installing mobile (Expo) dependencies..."
  (cd frontend/mobile && npm install)
  ok "Mobile dependencies installed"
else
  warn "Node.js not found — skipping Expo install."
  warn "Install Node from https://nodejs.org (LTS), then run: cd frontend/mobile && npm install"
fi

echo
info "You're set up."
echo
echo "  Product brief:  PRD.md"
echo "  Web app:        http://localhost:${WEB_PORT:-5173}"
echo "  API:            http://localhost:${BACKEND_PORT:-8000}/api/health/"
echo "  API docs-ish:   http://localhost:${BACKEND_PORT:-8000}/api/ask/  (POST)"
echo
echo "Useful commands:"
echo "  docker compose logs -f          # watch all logs"
echo "  docker compose down             # stop everything"
echo "  docker compose up -d            # start again later"
echo "  cd frontend/mobile && npm start # Expo / React Native"
echo
echo "Physical phone tip: set EXPO_PUBLIC_API_URL in .env to your laptop's LAN IP"
echo "(e.g. http://192.168.1.20:8000), then restart Expo."
echo
