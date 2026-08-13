#!/usr/bin/env bash
#
# One-command setup for AskScotty.
#
# Safe to run more than once — it never overwrites an existing .env, and
# re-running is the normal way to pick up new dependencies after a git pull.
#
# What you need first:
#   - Docker Desktop, installed and running   (runs the database + API)
#   - Node.js LTS                             (runs the app on phone/web)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

info() { echo -e "${BOLD}$*${NC}"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
step() { echo -e "\n${BOLD}$*${NC}"; }
dim()  { echo -e "${DIM}  $*${NC}"; }
fail() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

echo
info "AskScotty — setup"
dim "This takes a few minutes the first time. Downloads are slow; that's normal."

# ---------------------------------------------------------------------------
# 1. Environment files
# ---------------------------------------------------------------------------
step "1/5  Configuration files"

if [[ -f .env ]]; then
  ok ".env already exists (leaving your settings alone)"
else
  cp .env.example .env
  ok "Created .env"
fi

# Expo ONLY reads .env from its own folder, never the repo root. This is the
# single most common source of "why isn't my API URL working".
if [[ -f frontend/app/.env ]]; then
  ok "frontend/app/.env already exists"
else
  cp frontend/app/.env.example frontend/app/.env
  ok "Created frontend/app/.env"
fi

# Load the root .env so the ports below match what Docker actually publishes.
# Without this, changing BACKEND_PORT in .env makes this script check the wrong
# address and wrongly report the API as down.
set -a
# shellcheck disable=SC1091
source .env
set +a

BACKEND_PORT="${BACKEND_PORT:-8000}"
API_BASE="http://localhost:${BACKEND_PORT}"

# ---------------------------------------------------------------------------
# 2. Docker
# ---------------------------------------------------------------------------
step "2/5  Checking Docker"

command -v docker >/dev/null 2>&1 \
  || fail "Docker is not installed.
  Install Docker Desktop: https://www.docker.com/products/docker-desktop/
  Then open it, wait until it says Running, and run ./setup.sh again."

docker info >/dev/null 2>&1 \
  || fail "Docker is installed but not running.
  Open Docker Desktop and wait until it says Running, then run ./setup.sh again."
ok "Docker is running"

docker compose version >/dev/null 2>&1 \
  || fail "Docker Compose is missing. Update Docker Desktop and try again."
ok "Docker Compose is available"

# ---------------------------------------------------------------------------
# 3. Database + API
# ---------------------------------------------------------------------------
step "3/5  Starting the database and API"
dim "Building containers — first run pulls a few hundred MB. Please wait."

if ! docker compose up --build -d; then
  fail "Docker failed to start the services.
  See what went wrong with:  docker compose logs"
fi
ok "Containers started"

printf "  Waiting for the API to come up"
API_UP=""
for _ in $(seq 1 90); do
  if curl -fsS "${API_BASE}/api/health/" >/dev/null 2>&1; then
    API_UP="yes"
    break
  fi
  printf "."
  sleep 2
done
echo

if [[ -n "$API_UP" ]]; then
  ok "API is healthy at ${API_BASE}/api/health/"
else
  warn "The API has not responded yet at ${API_BASE}/api/health/"
  dim "It may still be starting. Check with:  docker compose logs -f backend"
  dim "If the port is already in use, change BACKEND_PORT in .env and re-run."
fi

# ---------------------------------------------------------------------------
# 4. Node
# ---------------------------------------------------------------------------
step "4/5  Checking Node.js"

NODE_OK=""
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  # React Native 0.86 supports even-numbered LTS releases only. Odd versions
  # (21, 23, ...) are experimental and break Metro in confusing ways.
  if (( NODE_MAJOR % 2 == 0 )) && (( NODE_MAJOR >= 20 )); then
    NODE_OK="yes"
    ok "Node $(node -v)"
  else
    warn "Node $(node -v) is not supported by React Native."
    dim "Install an LTS version (22 or 24) from https://nodejs.org"
    dim "Setup will continue, but the app may fail to start."
    NODE_OK="yes"  # try anyway; the warning is the important part
  fi
else
  warn "Node.js not found — skipping the app install."
  dim "Install Node LTS from https://nodejs.org, then run ./setup.sh again."
fi

# ---------------------------------------------------------------------------
# 5. Frontend
# ---------------------------------------------------------------------------
step "5/5  Installing the app"

if [[ -n "$NODE_OK" ]]; then
  dim "Running npm install in frontend/app — this takes a minute."
  if (cd frontend/app && npm install --no-fund --no-audit); then
    ok "App dependencies installed"
  else
    warn "npm install failed. Try again with:  cd frontend/app && npm install"
  fi
else
  warn "Skipped (no Node.js)"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
# Best-effort LAN IP, used for testing on a real phone.
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)"

echo
info "════════════════════════════════════════════════════════"
info "  Setup complete."
info "════════════════════════════════════════════════════════"
echo
echo "  Product brief   PRD.md"
echo "  API             ${API_BASE}/api/health/"
echo "  Try the API     ${API_BASE}/api/ask/   (clickable form in your browser)"
echo
info "Start the app:"
echo
echo "    cd frontend/app"
echo "    npx expo start"
echo
echo "  Then press:"
echo "    w  → open in your web browser"
echo "    i  → open the iPhone simulator (Mac + Xcode)"
echo "    a  → open the Android emulator"
echo "  Or scan the QR code with the Expo Go app on your phone."
echo
info "Useful commands:"
echo "    docker compose logs -f     watch the API logs"
echo "    docker compose down        stop the database and API"
echo "    docker compose up -d       start them again"
echo "    docker compose restart backend    after changing Python packages"
echo
if [[ -n "$LAN_IP" ]]; then
  info "Testing on a physical phone?"
  echo "  On a real phone, 'localhost' means the phone itself, not your laptop."
  echo "  Edit frontend/app/.env and set:"
  echo
  echo "      EXPO_PUBLIC_API_URL=http://${LAN_IP}:${BACKEND_PORT}"
  echo
  echo "  Then restart Expo. Your laptop and phone must be on the same Wi-Fi."
  echo
fi
