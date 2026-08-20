#!/usr/bin/env bash
# Start Metabase OSS against the local Price Paid Postgres.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MB_DIR="${ROOT}/metabase"
MAMBA_ROOT="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
JAVA_BIN="${MAMBA_ROOT}/envs/ppd/lib/jvm/bin/java"
# Fallback if conda puts java on PATH via activate
if [[ ! -x "${JAVA_BIN}" ]]; then
  JAVA_BIN="${MAMBA_ROOT}/envs/ppd/bin/java"
fi
JAR="${MB_DIR}/metabase.jar"
LOG="${MB_DIR}/metabase.log"
PIDFILE="${MB_DIR}/metabase.pid"

if [[ ! -x "${JAVA_BIN}" ]]; then
  echo "Java not found at ${JAVA_BIN}. Activate micromamba env ppd first."
  exit 1
fi
if [[ ! -f "${JAR}" ]]; then
  echo "Missing ${JAR}. Download with:"
  echo "  curl -L -o metabase/metabase.jar https://downloads.metabase.com/latest/metabase.jar"
  exit 1
fi

if [[ -f "${PIDFILE}" ]] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
  echo "Metabase already running (pid $(cat "${PIDFILE}"))."
  exit 0
fi

cd "${MB_DIR}"
# Keep Metabase app DB inside metabase/ so it stays with the project
export MB_DB_FILE="${MB_DIR}/metabase.db"
export MB_JETTY_PORT="${MB_JETTY_PORT:-3000}"

nohup "${JAVA_BIN}" -Xmx2g -jar "${JAR}" >"${LOG}" 2>&1 &
echo $! >"${PIDFILE}"
disown $! 2>/dev/null || true
echo "Metabase starting (pid $(cat "${PIDFILE}")). Log: ${LOG}"
echo "Waiting for http://localhost:${MB_JETTY_PORT} ..."

for i in $(seq 1 90); do
  if curl -sf "http://localhost:${MB_JETTY_PORT}/api/health" >/dev/null 2>&1; then
    echo "Metabase is up."
    echo "Keep this process running (or leave the background java job alive)."
    exit 0
  fi
  # If the java pid died early, fail fast
  if ! kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
    echo "Metabase process exited early. Check ${LOG}"
    exit 1
  fi
  sleep 2
done

echo "Timed out waiting for Metabase. Check ${LOG}"
exit 1
