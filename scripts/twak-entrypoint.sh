#!/bin/sh
# TWAK Docker entrypoint — initialises wallet on first boot, then serves.
#
# Required env vars (set in Coolify UI):
#   TWAK_ACCESS_ID    — from ~/.config/twak/config.json on your local machine
#   TWAK_HMAC_SECRET  — same file
#   TWAK_WALLET_NAME  — wallet name (default: alphaloop)

set -e

WALLET_NAME="${TWAK_WALLET_NAME:-alphaloop}"

if [ -z "$TWAK_ACCESS_ID" ] || [ -z "$TWAK_HMAC_SECRET" ]; then
  echo "[TWAK] ERROR: TWAK_ACCESS_ID and TWAK_HMAC_SECRET must be set in Coolify env vars."
  exit 1
fi

echo "[TWAK] Credentials OK. Checking wallet..."

# twak init creates the local agent wallet if it doesn't exist yet.
# The wallet is persisted in the twak-data volume across restarts.
twak init --name "$WALLET_NAME" 2>/dev/null && echo "[TWAK] Wallet ready." || echo "[TWAK] twak init skipped (already exists or non-interactive)."

echo "[TWAK] Starting REST server on 0.0.0.0:3000..."
exec twak serve --rest --host 0.0.0.0 --port 3000
