#!/usr/bin/env bash
# Stop the user-space PostgreSQL instance.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGDATA="${ROOT}/db/pgdata"
MAMBA_ROOT="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
PG_BIN="${MAMBA_ROOT}/envs/ppd/bin"

export PATH="${PG_BIN}:${PATH}"

if [[ ! -d "${PGDATA}" ]]; then
  echo "No Postgres data directory at ${PGDATA}."
  exit 0
fi

if pg_ctl -D "${PGDATA}" status >/dev/null 2>&1; then
  echo "Stopping Postgres..."
  pg_ctl -D "${PGDATA}" stop -m fast
else
  echo "Postgres is not running."
fi
