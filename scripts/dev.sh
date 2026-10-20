#!/usr/bin/env bash
# Start the local API and the web UI. Both bind to 127.0.0.1 only.
#
# - If the workbench is already running, this prints its address and exits instead of starting a copy.
# - Busy default ports are skipped: the API takes the first free port from 8000, the UI from 3000.
# - Ports you set explicitly must be free:  SOCIETYTWIN_API_PORT=8765 SOCIETYTWIN_WEB_PORT=3000 ./scripts/dev.sh
# Optional runtime: MATRAIX_ROOT, SOCIETYTWIN_RUNTIME_PYTHON (see docs/research-workbench.md).
set -euo pipefail
cd "$(dirname "$0")/.."

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
is_workbench() { curl -s --max-time 2 "http://127.0.0.1:$1/api/v1/health" 2>/dev/null | grep -q "API liveness only"; }
first_free() {
  local port=$1
  while port_busy "$port"; do
    port=$((port + 1))
    if [ "$port" -gt $(($1 + 50)) ]; then return 1; fi
  done
  echo "$port"
}
choose() {  # choose <explicit value or empty> <default start> <label>
  if [ -n "$1" ]; then
    if port_busy "$1"; then echo "Port $1 for the $3 is in use. Pick another or leave it unset." >&2; exit 1; fi
    echo "$1"
  else
    first_free "$2" || { echo "No free $3 port between $2 and $(($2 + 50))." >&2; exit 1; }
  fi
}

WEB_START="${SOCIETYTWIN_WEB_PORT:-3000}"
for port in $(seq "$WEB_START" $((WEB_START + 10))); do
  if port_busy "$port" && is_workbench "$port"; then
    echo "SocietyTwin is already running. Open http://127.0.0.1:$port"
    echo "To restart it, stop it first with Ctrl+C in the terminal that started it."
    exit 0
  fi
done

API_PORT=$(choose "${SOCIETYTWIN_API_PORT:-}" 8000 "API")
WEB_PORT=$(choose "${SOCIETYTWIN_WEB_PORT:-}" 3000 "web UI")
[ -x .venv/bin/python ] || { echo "Create the API environment first (see docs/research-workbench.md)." >&2; exit 1; }
[ -d frontend/node_modules ] || { echo "Run 'npm ci' in frontend/ first." >&2; exit 1; }

echo "Starting SocietyTwin: API on 127.0.0.1:$API_PORT, UI on http://127.0.0.1:$WEB_PORT"
PYTHONPATH="$PWD/src" SOCIETYTWIN_FRONTEND_ORIGINS="http://127.0.0.1:$WEB_PORT,http://localhost:$WEB_PORT" \
  .venv/bin/python -m uvicorn --factory societytwin.api.app:app_factory --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT
trap 'exit 130' INT TERM HUP
cd frontend
SOCIETYTWIN_API_ORIGIN="http://127.0.0.1:$API_PORT" npx next dev --hostname 127.0.0.1 --port "$WEB_PORT"
