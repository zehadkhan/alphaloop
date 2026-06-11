#!/usr/bin/env bash
# Remove the SQLite DB and let the backend recreate a clean schema.
# Run before June 22 to clear the 22 stale test trades.
set -euo pipefail
cd "$(dirname "$0")/.."

DB="storage/alphaloop.db"
if [ -f "$DB" ]; then
  BACKUP="${DB%.db}.backup.$(date +%Y%m%d_%H%M%S).db"
  cp "$DB" "$BACKUP"
  rm "$DB"
  echo "DB reset — backup saved to $BACKUP"
else
  echo "No DB found at $DB (nothing to reset)"
fi
