#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="${ROOT}/metabase/metabase.pid"
if [[ -f "${PIDFILE}" ]]; then
  pid="$(cat "${PIDFILE}")"
  if kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}"
    echo "Stopped Metabase (pid ${pid})."
  else
    echo "Stale pid file; Metabase not running."
  fi
  rm -f "${PIDFILE}"
else
  echo "No pid file; Metabase not tracked as running."
fi
