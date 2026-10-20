#!/usr/bin/env bash
# Fails if the built browser bundle contains server-side configuration or anything key-shaped.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d .next/static ] || { echo "Run a production build first (npx next build)"; exit 1; }
patterns='SOCIETYTWIN_API_ORIGIN|SOCIETYTWIN_STATE_DIR|SOCIETYTWIN_RUNTIME_PYTHON|MATRAIX_ROOT|_API_KEY|sk-[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{30,}|127\.0\.0\.1:87[0-9]{2}|/Users/|/home/'
if grep -rEl "$patterns" .next/static; then
  echo "FAIL: server configuration or key-shaped strings found in the client bundle"
  exit 1
fi
echo "OK: $(find .next/static -type f | wc -l | tr -d ' ') client files checked; no environment values, server paths or key-shaped strings"
