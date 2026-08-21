#!/usr/bin/env bash
#
# Load the prebuilt campus index into a deployed database.
#
#   ./scripts/restore_index.sh 'postgresql://user:pass@host/db?sslmode=require'
#
# Run this once, after the first deploy has applied its migrations — the dump
# carries rows only, not schema. Without it every campus question comes back
# with nothing found, which reads like a broken planner rather than an empty
# index.
#
# The dump is pg_dump output using `COPY ... FROM stdin` plus a \restrict meta
# command, so it needs a real psql client: `manage.py loaddata` and
# cursor.execute() both choke on it. If the host has no psql, the compose `db`
# container has one, and that path is used automatically.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DUMP="backend/fixtures/rag_index.sql.gz"

CONN="${1:-${DATABASE_URL:-}}"
if [[ -z "$CONN" ]]; then
  echo "usage: $0 <postgres-connection-string>" >&2
  echo "  or set DATABASE_URL" >&2
  exit 1
fi

[[ -f "$DUMP" ]] || { echo "No dump at $DUMP" >&2; exit 1; }

if command -v psql >/dev/null 2>&1; then
  run_psql() { psql "$CONN" "$@"; }
elif docker compose ps db --status running >/dev/null 2>&1; then
  echo "No psql on this machine — using the one in the compose db container."
  run_psql() { docker compose exec -T db psql "$CONN" "$@"; }
else
  echo "Needs either psql on PATH or the compose db container running." >&2
  echo "Start it with:  docker compose up -d db" >&2
  exit 1
fi

EXISTING="$(run_psql -tAc 'SELECT count(*) FROM rag_chunk;' 2>/dev/null | tr -d '[:space:]' || true)"
if [[ "${EXISTING:-}" =~ ^[0-9]+$ ]] && (( EXISTING > 0 )); then
  echo "Target already has ${EXISTING} chunks — nothing to do."
  echo "To replace it:  psql \"\$CONN\" -c 'TRUNCATE rag_document, rag_chunk CASCADE;'  then re-run."
  exit 0
fi

if [[ ! "${EXISTING:-}" =~ ^[0-9]+$ ]]; then
  echo "Could not read rag_chunk. Has the first deploy run its migrations yet?" >&2
  exit 1
fi

echo "Restoring the campus index (~1,400 chunks)…"
gunzip -c "$DUMP" | run_psql -q -v ON_ERROR_STOP=1

COUNT="$(run_psql -tAc 'SELECT count(*) FROM rag_chunk;' | tr -d '[:space:]')"
echo "Done — ${COUNT} chunks indexed."
