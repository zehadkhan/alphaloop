#!/bin/sh
# TWAK Docker entrypoint — creates wallet if needed, then starts REST server.
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

echo "[TWAK] Starting... wallet=${WALLET_NAME}"

# Create wallet if it doesn't exist yet in the persistent volume.
# 'twak wallet create' generates a fresh key and saves it to ~/.config/twak/
# The local wallet is then auto-bound when the REST server starts.
if ! twak wallet status --name "$WALLET_NAME" > /dev/null 2>&1; then
  echo "[TWAK] No wallet found — creating local agent wallet '${WALLET_NAME}'..."
  twak wallet create --name "$WALLET_NAME" && echo "[TWAK] Wallet created."
else
  echo "[TWAK] Wallet '${WALLET_NAME}' already exists — skipping create."
fi

echo "[TWAK] Starting REST server on 0.0.0.0:3000..."
exec twak serve --rest --host 0.0.0.0 --port 3000
