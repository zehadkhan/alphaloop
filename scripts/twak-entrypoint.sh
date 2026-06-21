#!/bin/sh
# TWAK Docker entrypoint — initialises credentials and wallet on first boot, then serves.
#
# Required env vars (set in Coolify UI):
#   TWAK_ACCESS_ID       — from ~/.config/twak/config.json on your local machine
#   TWAK_HMAC_SECRET     — same file
#   TWAK_WALLET_NAME     — wallet name (default: alphaloop)
#   TWAK_WALLET_PASSWORD — password used to create/unlock the wallet

set -e

WALLET_NAME="${TWAK_WALLET_NAME:-alphaloop}"
WALLET_PASSWORD="${TWAK_WALLET_PASSWORD:-${TWAK_HMAC_SECRET}}"

if [ -z "$TWAK_ACCESS_ID" ] || [ -z "$TWAK_HMAC_SECRET" ]; then
  echo "[TWAK] ERROR: TWAK_ACCESS_ID and TWAK_HMAC_SECRET must be set in Coolify env vars."
  exit 1
fi

echo "[TWAK] Credentials OK. Initializing..."

# Save credentials from env vars (idempotent)
twak init --name "$WALLET_NAME" 2>/dev/null || true

# Create wallet only if it doesn't already exist in the volume
if [ ! -f "$HOME/.twak/wallet.json" ]; then
  echo "[TWAK] No wallet found — creating wallet '$WALLET_NAME'..."
  twak wallet create --password "$WALLET_PASSWORD" \
    && echo "[TWAK] Wallet created successfully." \
    || echo "[TWAK] WARNING: wallet creation failed."
else
  echo "[TWAK] Wallet found. Ready."
fi

echo "[TWAK] Starting REST server on 0.0.0.0:3000..."
exec twak serve --rest --host 0.0.0.0 --port 3000
