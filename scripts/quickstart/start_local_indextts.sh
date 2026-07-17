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
  bash scripts/quickstart/start_local_indextts.sh [--host HOST] [--port PORT] [--device DEVICE] [--env FILE]

Options:
  --host HOST      Bind host for the local IndexTTS sidecar. Defaults to 127.0.0.1.
  --port PORT      Bind port. Defaults to OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL or 19092.
  --device DEVICE  Torch device for IndexTTS. Defaults to OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE or auto.
  --env FILE       Source a quickstart env file before starting the sidecar.
  --help           Show this help.
USAGE
}

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
host="${OPENTALKING_TTS_LOCAL_INDEXTTS_HOST:-127.0.0.1}"
port=""
device="${OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE:-}"

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
    --device)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --device" >&2
        exit 2
      fi
      device="$2"
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
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_RUNTIME_ROOT="${OPENTALKING_RUNTIME_ROOT:-$DIGITAL_HUMAN_HOME/runtimes}"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="${OPENTALKING_LOCAL_AUDIO_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT/local-audio}"
run_dir="$DIGITAL_HUMAN_HOME/run"
log_dir="$DIGITAL_HUMAN_HOME/logs"
mkdir -p "$run_dir" "$log_dir"

if [[ -z "$port" ]]; then
  port="${OPENTALKING_TTS_LOCAL_INDEXTTS_PORT:-}"
fi
if [[ -z "$port" && -n "${OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL:-}" ]]; then
  port="$(
    python3 - <<'PY'
import os
from urllib.parse import urlparse

url = os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL", "")
parsed = urlparse(url)
print(parsed.port or "")
PY
  )"
fi
port="${port:-19092}"
device="${device:-auto}"

resolve_indextts_python() {
  if [[ -n "${OPENTALKING_INDEXTTS_PYTHON:-}" ]]; then
    case "$OPENTALKING_INDEXTTS_PYTHON" in
      "$repo_root/.venv/"*)
        echo "Refusing to start local IndexTTS from the OpenTalking main venv: $OPENTALKING_INDEXTTS_PYTHON" >&2
        echo "Use OPENTALKING_INDEXTTS_VENV_DIR or OPENTALKING_INDEXTTS_PYTHON for the sidecar venv." >&2
        return 1
        ;;
    esac
    if [[ -x "$OPENTALKING_INDEXTTS_PYTHON" ]]; then
      printf '%s\n' "$OPENTALKING_INDEXTTS_PYTHON"
      return 0
    fi
    echo "OPENTALKING_INDEXTTS_PYTHON is not executable: $OPENTALKING_INDEXTTS_PYTHON" >&2
    return 1
  fi

  local candidate_dir=""
  for candidate_dir in \
    "${OPENTALKING_INDEXTTS_VENV_DIR:-}" \
    "$OPENTALKING_RUNTIME_ROOT/index-tts/venv" \
    "$repo_root/.venv-indextts" \
    "$DIGITAL_HUMAN_HOME/.venv-indextts"
  do
    [[ -n "$candidate_dir" ]] || continue
    case "$candidate_dir" in
      "$repo_root/.venv"|"$repo_root/.venv/"*)
        echo "Refusing to start local IndexTTS from the OpenTalking main venv: $candidate_dir" >&2
        echo "Use OPENTALKING_INDEXTTS_VENV_DIR or OPENTALKING_INDEXTTS_PYTHON for the sidecar venv." >&2
        return 1
        ;;
    esac
    if [[ -x "$candidate_dir/bin/python" ]]; then
      printf '%s\n' "$candidate_dir/bin/python"
      return 0
    fi
  done

  echo "Missing IndexTTS sidecar venv." >&2
  echo "Create it first with the IndexTTS runtime setup steps in the docs." >&2
  return 1
}

indextts_python="$(resolve_indextts_python)"

pid_file="$run_dir/local-indextts-$port.pid"
log_file="$log_dir/local-indextts-$port.log"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    if curl --max-time 2 -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      echo "Local IndexTTS is already running: pid=$old_pid port=$port"
      echo "Log: $log_file"
      exit 0
    fi
    echo "Stale Local IndexTTS pid file: pid=$old_pid port=$port" >&2
  fi
  rm -f "$pid_file"
fi

if quickstart_port_in_use "$port"; then
  echo "Local IndexTTS port $port is already in use." >&2
  quickstart_describe_port "$port" >&2 || true
  exit 1
fi

echo "Starting Local IndexTTS"
echo "  repo:    $repo_root"
echo "  python:  $indextts_python"
echo "  host:    $host"
echo "  port:    $port"
echo "  device:  $device"
echo "  log:     $log_file"

(
  cd "$repo_root"
  export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"
  export OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE="$device"
  setsid "$indextts_python" scripts/local_indextts_service.py --host "$host" --port "$port" >"$log_file" 2>&1 < /dev/null &
  echo "$!" >"$pid_file"
)

launcher_pid="$(cat "$pid_file" 2>/dev/null || true)"
if [[ -z "$launcher_pid" ]]; then
  echo "Failed to capture Local IndexTTS launcher pid." >&2
  exit 1
fi

for _ in {1..180}; do
  if curl --max-time 2 -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    actual_pid="$(ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)"
    if [[ -n "$actual_pid" ]]; then
      echo "$actual_pid" >"$pid_file"
    fi
    echo "Local IndexTTS is up: http://127.0.0.1:$port"
    echo "Log: $log_file"
    exit 0
  fi

  if ! kill -0 "$launcher_pid" >/dev/null 2>&1 && ! quickstart_port_in_use "$port"; then
    echo "Local IndexTTS exited during startup. Last log lines:" >&2
    tail -80 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  sleep 1
done

echo "Local IndexTTS did not become ready in 180s. Last log lines:" >&2
tail -80 "$log_file" >&2 || true
exit 1
