#!/bin/sh
# TWAK Docker entrypoint — sets up wallet on first boot then serves.
#
# On first run: creates a wallet from AGENT_PRIVATE_KEY env var.
# On subsequent runs: wallet already in volume, just serves.
#
# Required env vars:
#   AGENT_PRIVATE_KEY — your BSC private key (0x...)
#   TWAK_WALLET_NAME  — wallet name (default: alphaloop)

set -e

WALLET_NAME="${TWAK_WALLET_NAME:-alphaloop}"
TWAK_DATA="${HOME}/.config/twak"

echo "[TWAK] Starting... wallet=${WALLET_NAME}"

# Check if wallet already configured
if twak wallet status --name "$WALLET_NAME" > /dev/null 2>&1; then
  echo "[TWAK] Wallet '${WALLET_NAME}' already configured."
else
  echo "[TWAK] Wallet not found — setting up from AGENT_PRIVATE_KEY..."

  if [ -z "$AGENT_PRIVATE_KEY" ]; then
    echo "[TWAK] ERROR: AGENT_PRIVATE_KEY not set. Cannot create wallet."
    exit 1
  fi

  # Try import first, fall back to create if import not supported
  if twak wallet import --name "$WALLET_NAME" --key "$AGENT_PRIVATE_KEY" > /dev/null 2>&1; then
    echo "[TWAK] Wallet imported from private key."
  else
    echo "[TWAK] 'import --key' not available. Creating wallet..."
    echo "[TWAK] NOTE: Run 'docker exec -it alphaloop-twak twak wallet create --name ${WALLET_NAME}' to finish setup."
    echo "[TWAK] Starting server anyway (wallet setup can be done after)..."
  fi
fi

echo "[TWAK] Starting REST server on 0.0.0.0:3000..."
exec twak serve --rest --host 0.0.0.0 --port 3000
