#!/usr/bin/env bash
# Start the local API and the web UI. Both bind to 127.0.0.1 only.
#   SOCIETYTWIN_API_PORT (default 8000)   SOCIETYTWIN_WEB_PORT (default 3000)
# Optional runtime: MATRAIX_ROOT, SOCIETYTWIN_RUNTIME_PYTHON (see docs/research-workbench.md).
set -euo pipefail
cd "$(dirname "$0")/.."
API_PORT="${SOCIETYTWIN_API_PORT:-8000}"
WEB_PORT="${SOCIETYTWIN_WEB_PORT:-3000}"
for port in "$API_PORT" "$WEB_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use. Choose another with SOCIETYTWIN_API_PORT / SOCIETYTWIN_WEB_PORT." >&2
    exit 1
  fi
done
[ -x .venv/bin/python ] || { echo "Create the API environment first (see docs/research-workbench.md)." >&2; exit 1; }
[ -d frontend/node_modules ] || { echo "Run 'npm ci' in frontend/ first." >&2; exit 1; }
PYTHONPATH="$PWD/src" SOCIETYTWIN_FRONTEND_ORIGINS="http://127.0.0.1:$WEB_PORT,http://localhost:$WEB_PORT" \
  .venv/bin/python -m uvicorn --factory societytwin.api.app:app_factory --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT
cd frontend
SOCIETYTWIN_API_ORIGIN="http://127.0.0.1:$API_PORT" npx next dev --hostname 127.0.0.1 --port "$WEB_PORT"
