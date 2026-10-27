#!/usr/bin/env bash
# End-to-end: build the console, start the API with the Go gateway and the simulated model on a fresh database,
# seed cases, run Playwright. Needs PostgreSQL (CTA_E2E_ADMIN_URL points at a database that can create others).
set -euo pipefail
cd "$(dirname "$0")/.."
ADMIN_URL=${CTA_E2E_ADMIN_URL:-postgresql://ptp:ptp@127.0.0.1:5432/postgres}
DB_URL=${ADMIN_URL%/*}/cta_e2e
PORT=${CTA_E2E_PORT:-8090}
psql "$ADMIN_URL" -qc "DROP DATABASE IF EXISTS cta_e2e" -c "CREATE DATABASE cta_e2e"
(cd web && npm run build --silent)
CTA_DATABASE_URL=$DB_URL cta serve --local-stack --port "$PORT" > /tmp/cta-e2e.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 90); do curl -sf "http://127.0.0.1:$PORT/readyz" >/dev/null && break; sleep 1; done
ctasim seed --api "http://127.0.0.1:$PORT" --n 6 >/dev/null
(cd web && CTA_E2E_URL="http://127.0.0.1:$PORT" npx playwright test)
