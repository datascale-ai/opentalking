#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
default_home="$(cd -- "$repo_root/.." && pwd)"

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
if [[ -f "$env_file" ]]; then
  # shellcheck disable=SC1090
  source "$env_file"
fi

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/quickstart/status.sh [--api-port PORT] [--web-port PORT]

--api_port and --web_port are accepted as aliases for the dashed options.
USAGE
}

api_port="${OPENTALKING_API_PORT:-${OPENTALKING_UNIFIED_PORT:-8000}}"
web_port="${OPENTALKING_WEB_PORT:-5173}"
api_port_explicit=0
web_port_explicit=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-port|--api_port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      api_port="$2"
      api_port_explicit=1
      shift 2
      ;;
    --web-port|--web_port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      web_port="$2"
      web_port_explicit=1
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
omnirt_url="${OMNIRT_ENDPOINT:-http://127.0.0.1:9000}"
run_dir="$DIGITAL_HUMAN_HOME/run"

api_pid_file="$run_dir/opentalking-api-$api_port.pid"
web_pid_file="$run_dir/opentalking-web-$web_port.pid"
legacy_api_pid_file="$run_dir/opentalking-api.pid"
legacy_web_pid_file="$run_dir/opentalking-web.pid"

show_pid() {
  local name="$1"
  local pid_file="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      echo "$name: running pid=$pid"
      return
    fi
  fi
  echo "$name: not running from quickstart pid file"
}

check_url() {
  local label="$1"
  local url="$2"
  if curl --max-time 2 -fsS "$url" >/dev/null 2>&1; then
    echo "$label: ok ($url)"
  else
    echo "$label: unavailable ($url)"
  fi
}

echo "DIGITAL_HUMAN_HOME=$DIGITAL_HUMAN_HOME"

pid_port() {
  local pid_file="$1"
  local prefix="$2"
  local base
  base="$(basename "$pid_file")"
  base="${base#$prefix-}"
  echo "${base%.pid}"
}

show_api_glob() {
  local found=0
  shopt -s nullglob
  for pid_file in "$run_dir"/opentalking-api-*.pid; do
    found=1
    local discovered_port
    discovered_port="$(pid_port "$pid_file" "opentalking-api")"
    show_pid "OpenTalking API ($(basename "$pid_file"))" "$pid_file"
    check_url "OpenTalking API /models" "http://127.0.0.1:$discovered_port/models"
  done
  shopt -u nullglob
  if [[ "$found" == "0" ]]; then
    echo "OpenTalking API: not running from quickstart pid file"
  fi
}

show_web_glob() {
  local found=0
  shopt -s nullglob
  for pid_file in "$run_dir"/opentalking-web-*.pid; do
    found=1
    local discovered_port
    discovered_port="$(pid_port "$pid_file" "opentalking-web")"
    show_pid "OpenTalking frontend ($(basename "$pid_file"))" "$pid_file"
    check_url "OpenTalking frontend" "http://127.0.0.1:$discovered_port"
  done
  shopt -u nullglob
  if [[ "$found" == "0" ]]; then
    echo "OpenTalking frontend: not running from quickstart pid file"
  fi
}

if [[ "$api_port_explicit" == "1" ]]; then
  show_pid "OpenTalking API" "$api_pid_file"
  check_url "OpenTalking API /models" "http://127.0.0.1:$api_port/models"
else
  show_api_glob
fi
if [[ "$legacy_api_pid_file" != "$api_pid_file" ]]; then
  show_pid "OpenTalking API legacy pid" "$legacy_api_pid_file"
fi

if [[ "$web_port_explicit" == "1" ]]; then
  show_pid "OpenTalking frontend" "$web_pid_file"
  check_url "OpenTalking frontend" "http://127.0.0.1:$web_port"
else
  show_web_glob
fi
if [[ "$legacy_web_pid_file" != "$web_pid_file" ]]; then
  show_pid "OpenTalking frontend legacy pid" "$legacy_web_pid_file"
fi
show_pid "OmniRT Wav2Lip" "$run_dir/omnirt-wav2lip.pid"
show_pid "OmniRT FlashTalk endpoint" "$run_dir/omnirt-flashtalk.pid"
check_url "OmniRT /v1/audio2video/models" "$omnirt_url/v1/audio2video/models"
