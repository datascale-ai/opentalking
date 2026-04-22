#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${OPENTALKING_LOG_DIR:-$ROOT/logs}"
PID_FILE="${OPENTALKING_UNIFIED_PID_FILE:-$LOG_DIR/opentalking-unified-realtime.pid}"
LOG_FILE="${OPENTALKING_UNIFIED_LOG_FILE:-$LOG_DIR/opentalking-unified-realtime.log}"

mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    for _ in {1..30}; do
      if ! kill -0 "$OLD_PID" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if kill -0 "$OLD_PID" 2>/dev/null; then
      kill -9 "$OLD_PID" 2>/dev/null || true
    fi
  fi
  rm -f "$PID_FILE"
fi

DEFAULT_PYTHON="/data1/cw/miniconda3/envs/opentalking/bin/python"
if [[ -x "$DEFAULT_PYTHON" ]]; then
  export OPENTALKING_PYTHON_BIN="${OPENTALKING_PYTHON_BIN:-$DEFAULT_PYTHON}"
fi

nohup bash "$ROOT/scripts/start_unified.sh" "$@" >"$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" >"$PID_FILE"

sleep 2
if ! kill -0 "$NEW_PID" 2>/dev/null; then
  echo "Unified server failed to start. Check log: $LOG_FILE" >&2
  exit 1
fi

echo "Unified server restarted"
echo "PID: $NEW_PID"
echo "Log: $LOG_FILE"
if [[ -n "${OPENTALKING_DEBUG_DUMP_SPEECH_DIR:-}" ]]; then
  echo "Speech dumps: ${OPENTALKING_DEBUG_DUMP_SPEECH_DIR}"
else
  echo "Speech dumps: disabled"
fi
