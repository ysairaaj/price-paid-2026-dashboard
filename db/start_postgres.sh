#!/usr/bin/env bash
# Start a user-space PostgreSQL instance for the Price Paid dashboard.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGDATA="${ROOT}/db/pgdata"
PGPORT="${PGPORT:-5433}"
MAMBA_ROOT="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
PG_BIN="${MAMBA_ROOT}/envs/ppd/bin"

if [[ ! -x "${PG_BIN}/pg_ctl" ]]; then
  echo "PostgreSQL not found at ${PG_BIN}. Install with:"
  echo "  micromamba create -y -n ppd -c conda-forge postgresql=16 openjdk=21"
  exit 1
fi

export PATH="${PG_BIN}:${PATH}"

if [[ ! -d "${PGDATA}" ]]; then
  echo "Initializing new Postgres data directory at ${PGDATA}..."
  initdb -D "${PGDATA}" --auth=trust --username="$(whoami)" --encoding=UTF8 --locale=C
fi

if pg_ctl -D "${PGDATA}" status >/dev/null 2>&1; then
  echo "Postgres already running (data dir ${PGDATA})."
else
  echo "Starting Postgres on port ${PGPORT}..."
  pg_ctl -D "${PGDATA}" -l "${ROOT}/db/postgres.log" -o "-p ${PGPORT} -k ${ROOT}/db" start
fi

# Wait briefly for readiness
for _ in $(seq 1 30); do
  if pg_isready -h localhost -p "${PGPORT}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

if ! psql -h localhost -p "${PGPORT}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='price_paid'" | grep -q 1; then
  echo "Creating database price_paid..."
  createdb -h localhost -p "${PGPORT}" price_paid
fi

echo "Applying schema..."
psql -h localhost -p "${PGPORT}" -d price_paid -f "${ROOT}/db/schema.sql" >/dev/null

echo "Postgres ready: postgresql://localhost:${PGPORT}/price_paid"
