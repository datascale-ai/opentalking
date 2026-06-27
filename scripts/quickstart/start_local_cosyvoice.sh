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
  bash scripts/quickstart/start_local_cosyvoice.sh [--host HOST] [--port PORT] [--env FILE]

Options:
  --host HOST  Bind host for the local CosyVoice sidecar. Defaults to 127.0.0.1.
  --port PORT  Bind port. Defaults to OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL or 19090.
  --env FILE   Source a quickstart env file before starting the sidecar.
  --help       Show this help.
USAGE
}

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
host="${OPENTALKING_TTS_LOCAL_COSYVOICE_HOST:-127.0.0.1}"
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
  port="${OPENTALKING_TTS_LOCAL_COSYVOICE_PORT:-}"
fi
if [[ -z "$port" && -n "${OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL:-}" ]]; then
  port="$(
    python3 - <<'PY'
import os
from urllib.parse import urlparse

url = os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "")
parsed = urlparse(url)
print(parsed.port or "")
PY
  )"
fi
port="${port:-19090}"

resolve_cosyvoice_python() {
  if [[ -n "${OPENTALKING_COSYVOICE_PYTHON:-}" ]]; then
    if [[ -x "$OPENTALKING_COSYVOICE_PYTHON" ]]; then
      printf '%s\n' "$OPENTALKING_COSYVOICE_PYTHON"
      return 0
    fi
    echo "OPENTALKING_COSYVOICE_PYTHON is not executable: $OPENTALKING_COSYVOICE_PYTHON" >&2
    return 1
  fi

  local candidate_dir=""
  for candidate_dir in \
    "${OPENTALKING_COSYVOICE_VENV_DIR:-}" \
    "$repo_root/.venv-cosyvoice" \
    "$DIGITAL_HUMAN_HOME/.venv-cosyvoice" \
    "/root/cosyvoice/.venv"
  do
    [[ -n "$candidate_dir" ]] || continue
    if [[ -x "$candidate_dir/bin/python" ]]; then
      printf '%s\n' "$candidate_dir/bin/python"
      return 0
    fi
  done

  echo "Missing CosyVoice sidecar venv." >&2
  echo "Create it first: OPENTALKING_COSYVOICE_VENV_DIR=\"$repo_root/.venv-cosyvoice\" bash scripts/prepare_cosyvoice_venv.sh" >&2
  return 1
}

cosy_python="$(resolve_cosyvoice_python)"
case "$cosy_python" in
  "$repo_root/.venv/"*)
    echo "Refusing to start local CosyVoice from the OpenTalking main venv: $cosy_python" >&2
    echo "Use OPENTALKING_COSYVOICE_VENV_DIR or OPENTALKING_COSYVOICE_PYTHON for the sidecar venv." >&2
    exit 1
    ;;
esac

cosy_site_packages="$($cosy_python - <<'PY'
import sysconfig

print(sysconfig.get_paths().get("purelib", ""))
PY
)"
cosy_trt_lib_dir="$cosy_site_packages/tensorrt_libs"
if [[ -d "$cosy_trt_lib_dir" ]]; then
  export LD_LIBRARY_PATH="$cosy_trt_lib_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

pid_file="$run_dir/local-cosyvoice-$port.pid"
log_file="$log_dir/local-cosyvoice-$port.log"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    if curl --max-time 2 -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      echo "Local CosyVoice is already running: pid=$old_pid port=$port"
      echo "Log: $log_file"
      exit 0
    fi
    echo "Stale Local CosyVoice pid file: pid=$old_pid port=$port" >&2
  fi
  rm -f "$pid_file"
fi

if quickstart_port_in_use "$port"; then
  echo "Local CosyVoice port $port is already in use." >&2
  quickstart_describe_port "$port" >&2 || true
  exit 1
fi

echo "Starting Local CosyVoice"
echo "  repo:    $repo_root"
echo "  python:  $cosy_python"
echo "  host:    $host"
echo "  port:    $port"
echo "  log:     $log_file"
if [[ -d "$cosy_trt_lib_dir" ]]; then
  echo "  trt lib: $cosy_trt_lib_dir"
fi

(
  cd "$repo_root"
  export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"
  export OPENTALKING_TTS_LOCAL_COSYVOICE_PRELOAD="${OPENTALKING_TTS_LOCAL_COSYVOICE_PRELOAD:-1}"
  if declare -F quickstart_detach >/dev/null 2>&1; then
    quickstart_detach "$log_file" "$cosy_python" scripts/local_cosyvoice_service.py --host "$host" --port "$port" >"$pid_file"
  else
    setsid "$cosy_python" scripts/local_cosyvoice_service.py --host "$host" --port "$port" >"$log_file" 2>&1 < /dev/null &
    echo "$!" >"$pid_file"
  fi
)

pid="$(cat "$pid_file" 2>/dev/null || true)"
if [[ -z "$pid" ]]; then
  echo "Failed to capture Local CosyVoice pid." >&2
  exit 1
fi

for _ in {1..120}; do
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "Local CosyVoice exited during startup. Last log lines:" >&2
    tail -80 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  if curl --max-time 2 -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    echo "Local CosyVoice is up: http://127.0.0.1:$port"
    exit 0
  fi
  sleep 1
done

echo "Local CosyVoice did not become ready in 120s. Last log lines:" >&2
tail -80 "$log_file" >&2 || true
exit 1
