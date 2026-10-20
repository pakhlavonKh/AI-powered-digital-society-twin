#!/usr/bin/env bash
# Browser flow against the artificial fixtures: throwaway copies of tests/fixtures/artificial_experiment and
# tests/fixtures/artificial_tuik_package (national pipeline), all state and generated data in a temporary directory,
# a temporary state directory, no MatrAIx runtime and no provider keys.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
API_PORT="${E2E_API_PORT:-8766}"
WEB_PORT="${E2E_WEB_PORT:-3100}"
WORK="$(mktemp -d)"
cp -R tests/fixtures/artificial_experiment "$WORK/experiment"
cp -R tests/fixtures/artificial_tuik_package "$WORK/tuik_package"
printf 'datasets: []\n' > "$WORK/manifest.yaml"
cleanup() { [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true; [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
env -i PATH="$PATH" HOME="$HOME" PYTHONPATH="$REPO/src" \
  SOCIETYTWIN_EXPERIMENT_ROOT="$WORK/experiment" SOCIETYTWIN_STATE_DIR="$WORK/state" MATRAIX_ROOT="$WORK/no-matraix" \
  SOCIETYTWIN_DATA_MANIFEST="$WORK/manifest.yaml" SOCIETYTWIN_TUIK_PACKAGE="$WORK/tuik_package" \
  SOCIETYTWIN_TUIK_MAPPING="$REPO/tests/fixtures/artificial_tuik_package_mapping.yaml" \
  SOCIETYTWIN_CONTROLS_DIR="$WORK/controls" SOCIETYTWIN_POPULATIONS_DIR="$WORK/populations" \
  SOCIETYTWIN_FRONTEND_ORIGINS="http://127.0.0.1:$WEB_PORT" \
  "$REPO/.venv/bin/python" -m uvicorn --factory societytwin.api.app:app_factory --host 127.0.0.1 --port "$API_PORT" > "$WORK/api.log" 2>&1 &
API_PID=$!
cd frontend
SOCIETYTWIN_API_ORIGIN="http://127.0.0.1:$API_PORT" npx next build > "$WORK/build.log" 2>&1 || { cat "$WORK/build.log"; exit 1; }
SOCIETYTWIN_API_ORIGIN="http://127.0.0.1:$API_PORT" npx next start --hostname 127.0.0.1 --port "$WEB_PORT" > "$WORK/web.log" 2>&1 &
WEB_PID=$!
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$WEB_PORT/api/v1/health" > /dev/null && break; sleep 1; done
E2E_WEB_PORT="$WEB_PORT" npx playwright test "$@"
