#!/usr/bin/env bash
# AlphaLoop — Stop all running processes (terminal mode)

cd "$(dirname "$0")/.."

echo "Stopping AlphaLoop..."

# Kill by saved PID files
for pidfile in storage/agent.pid storage/dashboard.pid; do
  if [ -f "$pidfile" ]; then
    PID=$(cat "$pidfile")
    if kill -0 "$PID" 2>/dev/null; then
      kill "$PID" && echo "  Stopped PID $PID ($(basename $pidfile .pid))"
    fi
    rm -f "$pidfile"
  fi
done

# Kill by port as fallback
lsof -ti :8000 | xargs kill -9 2>/dev/null && echo "  Killed process on :8000" || true
lsof -ti :3001 | xargs kill -9 2>/dev/null && echo "  Killed process on :3001" || true

echo "Done."
