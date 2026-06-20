#!/bin/sh
# TWAK Docker entrypoint — passes credentials and starts REST server.
#
# Required env vars (set in Coolify UI):
#   TWAK_ACCESS_ID    — from ~/.config/twak/config.json on your local machine
#   TWAK_HMAC_SECRET  — same file
#   AGENT_PRIVATE_KEY — BSC private key (0x...)
#   TWAK_WALLET_NAME  — wallet name (default: alphaloop)

set -e

WALLET_NAME="${TWAK_WALLET_NAME:-alphaloop}"

# Validate required credentials
if [ -z "$TWAK_ACCESS_ID" ] || [ -z "$TWAK_HMAC_SECRET" ]; then
  echo "[TWAK] ERROR: TWAK_ACCESS_ID and TWAK_HMAC_SECRET must be set."
  echo "[TWAK] Find them in ~/.config/twak/config.json on your local machine."
  echo "[TWAK] Add them as env vars in Coolify and redeploy."
  exit 1
fi

echo "[TWAK] Credentials found. Starting REST server on 0.0.0.0:3000..."
exec twak serve --rest --host 0.0.0.0 --port 3000
