#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
default_home="$(cd -- "$repo_root/.." && pwd)"
# shellcheck disable=SC1091
source "$script_dir/_helpers.sh"

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
quickstart_source_env "$env_file"

# Do not let frontend tooling inherit notebook, Codex, or provider credentials.
unset OPENAI_API_KEY OPENAI_ADMIN_KEY OPENAI_BASE_URL
unset DASHSCOPE_API_KEY DASHSCOPE_API_TOKEN
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET
unset JUPYTER_TOKEN

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/quickstart/start_frontend.sh [--host HOST] [--web-port PORT] [--api-port PORT]

Defaults:
  HOST = OPENTALKING_WEB_HOST or 0.0.0.0
  WEB PORT = OPENTALKING_WEB_PORT or 5173
  API PORT = VITE_BACKEND_PORT, OPENTALKING_API_PORT, OPENTALKING_UNIFIED_PORT, or 8000

--port stays available as a compatibility alias for --web-port.
--web_port and --api_port are also accepted.
USAGE
}

web_host="${OPENTALKING_WEB_HOST:-0.0.0.0}"
web_port="${OPENTALKING_WEB_PORT:-5173}"
backend_port="${VITE_BACKEND_PORT:-${OPENTALKING_API_PORT:-${OPENTALKING_UNIFIED_PORT:-8000}}}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      web_host="$2"
      shift 2
      ;;
    --port|--web-port|--web_port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      web_port="$2"
      shift 2
      ;;
    --api-port|--api_port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      backend_port="$2"
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

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"

run_dir="$DIGITAL_HUMAN_HOME/run"
log_dir="$DIGITAL_HUMAN_HOME/logs"
pid_file="$run_dir/opentalking-web-$web_port.pid"
log_file="$log_dir/opentalking-web-$web_port.log"
web_dir="$repo_root/apps/web"

mkdir -p "$run_dir" "$log_dir"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "OpenTalking frontend is already running: pid=$old_pid port=$web_port"
    echo "Log: $log_file"
    exit 0
  fi
  rm -f "$pid_file"
fi

if quickstart_port_in_use "$web_port"; then
  echo "OpenTalking frontend port $web_port is already in use." >&2
  echo "Stop the existing service first, or choose another --web-port." >&2
  quickstart_describe_port "$web_port" >&2 || true
  exit 1
fi

if [[ ! -d "$web_dir/node_modules" ]]; then
  echo "Installing frontend dependencies with npm ci ..."
  (cd "$web_dir" && npm ci)
fi

echo "Starting OpenTalking frontend"
echo "  web:  $web_dir"
echo "  url:  http://127.0.0.1:$web_port"
echo "  log:  $log_file"
echo "  api:  http://127.0.0.1:$backend_port"

(
  cd "$web_dir"
  export VITE_BACKEND_PORT="$backend_port"
  if [[ "${OPENTALKING_WEB_DEV_SERVER:-0}" == "1" ]]; then
    quickstart_detach "$log_file" ./node_modules/.bin/vite --host "$web_host" --port "$web_port" --strictPort >"$pid_file"
  else
    npm run build >>"$log_file" 2>&1
    quickstart_detach "$log_file" ./node_modules/.bin/vite preview --host "$web_host" --port "$web_port" --strictPort >"$pid_file"
  fi
)

pid="$(cat "$pid_file" 2>/dev/null || true)"
if [[ -z "$pid" ]]; then
  echo "Failed to capture OpenTalking frontend pid." >&2
  exit 1
fi

for _ in {1..60}; do
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "OpenTalking frontend exited during startup. Last log lines:" >&2
    tail -80 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  if curl --max-time 2 -fsS "http://127.0.0.1:$web_port" >/dev/null 2>&1; then
    echo "OpenTalking frontend is up: http://127.0.0.1:$web_port"
    exit 0
  fi
  sleep 1
done

echo "OpenTalking frontend did not become ready in 60s. Last log lines:" >&2
tail -80 "$log_file" >&2 || true
exit 1
