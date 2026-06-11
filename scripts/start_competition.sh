#!/usr/bin/env bash
# AlphaLoop — Competition Launch Script
# Starts the agent + dashboard via Docker Compose.
# TWAK server must be running on the HOST before this script runs.
#
# Usage:
#   chmod +x scripts/start_competition.sh
#   ./scripts/start_competition.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "======================================"
echo " AlphaLoop Competition Launch"
echo "======================================"

# ── 1. Sanity checks ──────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in your values."
  exit 1
fi

source .env 2>/dev/null || true

if [ "${ENVIRONMENT:-testnet}" != "mainnet" ]; then
  echo "ERROR: ENVIRONMENT is not 'mainnet'. Edit .env before going live."
  exit 1
fi

if [ "${DRY_RUN:-true}" == "true" ]; then
  echo "WARNING: DRY_RUN=true — trades will NOT hit the chain."
  read -p "Continue with dry run? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || exit 1
fi

echo "✓ Config OK"
echo "  ENVIRONMENT      = ${ENVIRONMENT}"
echo "  DRY_RUN          = ${DRY_RUN}"
echo "  COMPETITION_MODE = ${COMPETITION_MODE:-false}"
echo "  TRADING_PAIR     = ${TRADING_PAIR:-BNB/USDT}"
echo ""

# ── 2. TWAK server health check ───────────────────────────────
TWAK_URL="${TWAK_REST_URL:-http://localhost:7777}"
echo "Checking TWAK server at ${TWAK_URL} ..."
if curl -sf "${TWAK_URL}/health" > /dev/null 2>&1; then
  echo "✓ TWAK server online"
else
  echo ""
  echo "TWAK server not responding. Start it first:"
  echo "  twak serve"
  echo ""
  read -p "Continue without TWAK (uses web3.py signing)? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || exit 1
fi

# ── 3. Reset DB for clean competition start ────────────────────
DB_PATH="storage/alphaloop.db"
if [ -f "$DB_PATH" ]; then
  echo ""
  echo "Existing DB found: $DB_PATH"
  read -p "Reset DB for clean start? (removes test trades) [y/N] " answer
  if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
    BACKUP="${DB_PATH%.db}.backup.$(date +%Y%m%d_%H%M%S).db"
    cp "$DB_PATH" "$BACKUP"
    rm "$DB_PATH"
    echo "✓ DB reset — backup: $BACKUP"
  fi
fi

# ── 4. Build and start via Docker Compose ─────────────────────
echo ""
echo "Building Docker images..."
docker compose build

echo ""
echo "Starting containers..."
docker compose up -d

echo ""
echo "Waiting for backend health check..."
for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ Backend healthy"
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "ERROR: Backend did not become healthy. Check logs:"
    echo "  docker compose logs alphaloop"
    exit 1
  fi
  sleep 3
done

# ── 5. Trigger on-chain registration ──────────────────────────
echo ""
echo "Triggering on-chain registration (ERC-8004)..."
REGISTER_RESULT=$(curl -sf -X POST http://localhost:8000/competition/register 2>&1 || echo '{"ok":false}')
echo "  $REGISTER_RESULT"

# ── 6. Show status ────────────────────────────────────────────
echo ""
echo "======================================"
echo " AlphaLoop is LIVE"
echo "======================================"
curl -sf http://localhost:8000/status | python3 -m json.tool 2>/dev/null || true
echo ""
echo " Backend  : http://localhost:8000"
echo " Dashboard: http://localhost:3001"
echo ""
echo " Useful commands:"
echo "   docker compose logs -f alphaloop     # stream backend logs"
echo "   docker compose ps                    # container health"
echo "   curl localhost:8000/competition/status | python3 -m json.tool"
echo "   curl localhost:8000/competition/scan  | python3 -m json.tool"
echo ""
echo " Competition window: June 22–28 UTC"
echo " DO NOT restart during the trading window unless the agent is down."
echo "======================================"
