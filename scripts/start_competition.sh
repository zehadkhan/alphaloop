#!/usr/bin/env bash
# AlphaLoop — Competition Launch Script
# Default: terminal mode (no Docker needed)
# Optional: --docker flag to use Docker Compose instead
#
# Usage:
#   bash scripts/start_competition.sh           # terminal mode
#   bash scripts/start_competition.sh --docker  # docker mode

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

USE_DOCKER=false
[[ "${1:-}" == "--docker" ]] && USE_DOCKER=true

echo ""
echo "========================================"
echo "  AlphaLoop — Competition Launch"
echo "  Mode: $([ "$USE_DOCKER" = true ] && echo 'Docker' || echo 'Terminal')"
echo "========================================"
echo ""

# ── 1. Env checks ─────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "ERROR: .env not found."
  exit 1
fi

source .env 2>/dev/null || true

if [ "${ENVIRONMENT:-testnet}" != "mainnet" ]; then
  echo "ERROR: ENVIRONMENT=${ENVIRONMENT:-testnet} — must be 'mainnet' to compete."
  echo "       Edit .env and set ENVIRONMENT=mainnet"
  exit 1
fi

if [ "${DRY_RUN:-true}" == "true" ]; then
  echo "WARNING: DRY_RUN=true — trades will NOT hit the chain."
  read -rp "Continue with dry run? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1
fi

echo "  ENVIRONMENT      = ${ENVIRONMENT}"
echo "  DRY_RUN          = ${DRY_RUN:-false}"
echo "  COMPETITION_MODE = ${COMPETITION_MODE:-false}"
echo "  TRADING_PAIR     = ${TRADING_PAIR:-ETH/USDT}"
echo ""

# ── 2. TWAK check ─────────────────────────────────────────────────────────
TWAK_URL="${TWAK_REST_URL:-http://localhost:1337}"
if curl -sf "${TWAK_URL}/health" > /dev/null 2>&1; then
  echo "✓ TWAK server online at ${TWAK_URL}"
else
  echo "✗ TWAK not running at ${TWAK_URL}"
  echo "  Start it first:  twak serve"
  echo ""
  read -rp "Continue without TWAK (web3 signing fallback)? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1
  echo "  Continuing without TWAK..."
fi
echo ""

# ── 3. Docker mode ────────────────────────────────────────────────────────
if [ "$USE_DOCKER" = true ]; then
  echo "Building Docker images..."
  docker compose build
  echo ""
  echo "Starting containers..."
  docker compose up -d
  echo ""
  echo "Waiting for agent health..."
  for i in $(seq 1 20); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
      echo "✓ Agent healthy"
      break
    fi
    [ "$i" -eq 20 ] && echo "ERROR: Agent didn't start. Run: docker compose logs alphaloop" && exit 1
    sleep 3
  done
  _show_status
  exit 0
fi

# ── 4. Terminal mode ──────────────────────────────────────────────────────

# Kill any existing instances
echo "Stopping any existing processes..."
lsof -ti :8000 | xargs kill -9 2>/dev/null && echo "  Stopped process on :8000" || true
lsof -ti :3001 | xargs kill -9 2>/dev/null && echo "  Stopped process on :3001" || true
sleep 1

mkdir -p storage

# Start agent
echo ""
echo "Starting agent (mainnet, competition mode)..."
nohup .venv/bin/python3 -m uvicorn agent.main:app \
  --host 0.0.0.0 --port 8000 \
  > storage/uvicorn.log 2>&1 &
AGENT_PID=$!
echo "$AGENT_PID" > storage/agent.pid
echo "  PID: $AGENT_PID  |  Log: storage/uvicorn.log"

# Wait for agent to be ready
echo "  Waiting for agent..."
for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "  ✓ Agent healthy"
    break
  fi
  [ "$i" -eq 20 ] && echo "  ERROR: Agent didn't start. Check storage/uvicorn.log" && exit 1
  sleep 2
done

# Start dashboard
echo ""
echo "Starting dashboard..."
cd dashboard
nohup npm run dev > ../storage/dashboard.log 2>&1 &
DASH_PID=$!
echo "$DASH_PID" > ../storage/dashboard.pid
cd ..
echo "  PID: $DASH_PID  |  Log: storage/dashboard.log"

# Wait for dashboard
sleep 5
if curl -sf http://localhost:3001 > /dev/null 2>&1; then
  echo "  ✓ Dashboard ready"
else
  echo "  Dashboard still starting — check storage/dashboard.log if it doesn't load"
fi

# ── 5. Register on-chain ──────────────────────────────────────────────────
echo ""
echo "Triggering on-chain registration..."
REG=$(curl -sf -X POST http://localhost:8000/competition/register 2>&1 || echo '{"ok":false}')
echo "  $REG"

# ── 6. Final status ───────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  AlphaLoop is LIVE"
echo "========================================"
curl -sf http://localhost:8000/health 2>/dev/null | python3 -m json.tool 2>/dev/null || true
echo ""
echo "  Agent     →  http://localhost:8000"
echo "  Dashboard →  http://localhost:3001"
echo "  Docs      →  http://localhost:8000/docs"
echo ""
echo "  Useful commands:"
echo "    tail -f storage/uvicorn.log       # live agent logs"
echo "    tail -f storage/dashboard.log     # dashboard logs"
echo "    curl localhost:8000/competition/status | python3 -m json.tool"
echo "    curl -X POST localhost:8000/run   # trigger a manual cycle"
echo "    bash scripts/stop.sh              # stop everything"
echo ""
echo "  Competition window: June 22–28 UTC"
echo "========================================"
