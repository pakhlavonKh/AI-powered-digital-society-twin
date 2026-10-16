#!/usr/bin/env bash
# Regenerate frontend/openapi.json and the typed TypeScript client from the FastAPI app.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src .venv/bin/python -m societytwin.api.openapi_export frontend/openapi.json
if [ -d frontend/node_modules ]; then
  (cd frontend && npx --no-install openapi-typescript openapi.json -o src/lib/api/schema.d.ts)
fi
