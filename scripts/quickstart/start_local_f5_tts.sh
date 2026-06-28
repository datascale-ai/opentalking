#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
default_home="$(cd -- "$repo_root/.." && pwd)"
# shellcheck disable=SC1091
source "$script_dir/_helpers.sh"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/quickstart/start_local_f5_tts.sh [--host HOST] [--port PORT] [--env FILE]

Options:
  --host HOST  Bind host for the local F5-TTS sidecar. Defaults to 127.0.0.1.
  --port PORT  Bind port. Defaults to OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL or 19095.
  --env FILE   Source a quickstart env file before starting the sidecar.
  --help       Show this help.
USAGE
}

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
host="${OPENTALKING_TTS_LOCAL_F5_TTS_HOST:-127.0.0.1}"
port=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --host" >&2
        exit 2
      fi
      host="$2"
      shift 2
      ;;
    --port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --port" >&2
        exit 2
      fi
      port="$2"
      shift 2
      ;;
    --env)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --env" >&2
        exit 2
      fi
      env_file="$2"
      export OPENTALKING_QUICKSTART_ENV="$env_file"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

quickstart_source_env "$env_file"

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
run_dir="$DIGITAL_HUMAN_HOME/run"
log_dir="$DIGITAL_HUMAN_HOME/logs"
mkdir -p "$run_dir" "$log_dir"

if [[ -z "$port" ]]; then
  port="${OPENTALKING_TTS_LOCAL_F5_TTS_PORT:-}"
fi
if [[ -z "$port" && -n "${OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL:-}" ]]; then
  port="$(
    python3 - <<'PY'
import os
from urllib.parse import urlparse

url = os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL", "")
parsed = urlparse(url)
print(parsed.port or "")
PY
  )"
fi
port="${port:-19095}"

resolve_f5_python() {
  if [[ -n "${OPENTALKING_F5_TTS_PYTHON:-}" ]]; then
    case "$OPENTALKING_F5_TTS_PYTHON" in
      "$repo_root/.venv/"*)
        echo "Refusing to start local F5-TTS from the OpenTalking main venv: $OPENTALKING_F5_TTS_PYTHON" >&2
        echo "Use OPENTALKING_F5_TTS_VENV_DIR or OPENTALKING_F5_TTS_PYTHON for the sidecar venv." >&2
        return 1
        ;;
    esac
    if [[ -x "$OPENTALKING_F5_TTS_PYTHON" ]]; then
      printf '%s\n' "$OPENTALKING_F5_TTS_PYTHON"
      return 0
    fi
    echo "OPENTALKING_F5_TTS_PYTHON is not executable: $OPENTALKING_F5_TTS_PYTHON" >&2
    return 1
  fi

  local candidate_dir=""
  for candidate_dir in \
    "${OPENTALKING_F5_TTS_VENV_DIR:-}" \
    "$repo_root/.venv-f5-tts" \
    "$DIGITAL_HUMAN_HOME/.venv-f5-tts" \
    "/home/zhongyi/models/local-audio/runtime/.venv-f5-tts"
  do
    [[ -n "$candidate_dir" ]] || continue
    if [[ -x "$candidate_dir/bin/python" ]]; then
      printf '%s\n' "$candidate_dir/bin/python"
      return 0
    fi
  done

  echo "Missing F5-TTS sidecar venv." >&2
  echo "Create it first: python3 -m venv $repo_root/.venv-f5-tts && $repo_root/.venv-f5-tts/bin/pip install -e /home/zhongyi/models/local-audio/runtime/F5-TTS fastapi 'uvicorn[standard]' soundfile" >&2
  return 1
}

f5_python="$(resolve_f5_python)"

pid_file="$run_dir/local-f5-tts-$port.pid"
log_file="$log_dir/local-f5-tts-$port.log"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    if curl --max-time 2 -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      echo "Local F5-TTS is already running: pid=$old_pid port=$port"
      echo "Log: $log_file"
      exit 0
    fi
    echo "Stale Local F5-TTS pid file: pid=$old_pid port=$port" >&2
  fi
  rm -f "$pid_file"
fi

if quickstart_port_in_use "$port"; then
  echo "Local F5-TTS port $port is already in use." >&2
  quickstart_describe_port "$port" >&2 || true
  exit 1
fi

echo "Starting Local F5-TTS"
echo "  repo:    $repo_root"
echo "  python:  $f5_python"
echo "  host:    $host"
echo "  port:    $port"
echo "  log:     $log_file"

(
  cd "$repo_root"
  export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"
  export OPENTALKING_TTS_LOCAL_F5_TTS_PRELOAD="${OPENTALKING_TTS_LOCAL_F5_TTS_PRELOAD:-1}"
  if declare -F quickstart_detach >/dev/null 2>&1; then
    quickstart_detach "$log_file" "$f5_python" scripts/local_f5_tts_service.py --host "$host" --port "$port" >"$pid_file"
  else
    setsid "$f5_python" scripts/local_f5_tts_service.py --host "$host" --port "$port" >"$log_file" 2>&1 < /dev/null &
    echo "$!" >"$pid_file"
  fi
)

pid="$(cat "$pid_file" 2>/dev/null || true)"
if [[ -z "$pid" ]]; then
  echo "Failed to capture Local F5-TTS pid." >&2
  exit 1
fi

for _ in {1..180}; do
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "Local F5-TTS exited during startup. Last log lines:" >&2
    tail -80 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  if curl --max-time 2 -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    echo "Local F5-TTS is up: http://127.0.0.1:$port"
    exit 0
  fi
  sleep 1
done

echo "Local F5-TTS did not become ready in 180s. Last log lines:" >&2
tail -80 "$log_file" >&2 || true
exit 1
