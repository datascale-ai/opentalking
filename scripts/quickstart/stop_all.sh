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
  bash scripts/quickstart/stop_all.sh [--api-port PORT] [--web-port PORT]

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
run_dir="$DIGITAL_HUMAN_HOME/run"

stop_pid_file() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name: not started by quickstart scripts"
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "$name: stale pid file removed"
    rm -f "$pid_file"
    return
  fi

  echo "Stopping $name: pid=$pid"
  kill "$pid" >/dev/null 2>&1 || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$pid_file"
      echo "$name: stopped"
      return
    fi
    sleep 0.5
  done

  echo "$name: still running, sending SIGKILL"
  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$pid_file"
}

stop_pid_glob() {
  local name="$1"
  local pattern="$2"
  local found=0
  shopt -s nullglob
  for pid_file in $pattern; do
    found=1
    stop_pid_file "$name ($(basename "$pid_file"))" "$pid_file"
  done
  shopt -u nullglob
  if [[ "$found" == "0" ]]; then
    echo "$name: not started by quickstart scripts"
  fi
}

stop_unified_port() {
  local port="$1"
  local pids
  pids="$(pgrep -f "$repo_root/.venv/bin/.*opentalking-unified" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  for pid in $pids; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    if tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -qx "OPENTALKING_UNIFIED_PORT=$port"; then
      echo "Stopping OpenTalking API unified residue: pid=$pid port=$port"
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}

stop_unified_all() {
  local pids
  pids="$(pgrep -f "$repo_root/.venv/bin/.*opentalking-unified" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  for pid in $pids; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    if [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)" == "$repo_root" ]]; then
      echo "Stopping OpenTalking API unified residue: pid=$pid"
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}

stop_vite_port() {
  local port="$1"
  local pids
  pids="$(pgrep -f "$repo_root/apps/web/node_modules/.bin/vite .*--port $port" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  for pid in $pids; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    echo "Stopping OpenTalking frontend Vite residue: pid=$pid port=$port"
    kill "$pid" >/dev/null 2>&1 || true
  done
}

stop_vite_all() {
  local pids
  pids="$(pgrep -f "$repo_root/apps/web/node_modules/.bin/vite .*--port" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  for pid in $pids; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    echo "Stopping OpenTalking frontend Vite residue: pid=$pid"
    kill "$pid" >/dev/null 2>&1 || true
  done
}

if [[ "$api_port_explicit" == "1" ]]; then
  stop_pid_file "OpenTalking API" "$run_dir/opentalking-api-$api_port.pid"
  stop_unified_port "$api_port"
else
  stop_pid_glob "OpenTalking API" "$run_dir/opentalking-api-*.pid"
  stop_unified_all
fi

if [[ "$web_port_explicit" == "1" ]]; then
  stop_pid_file "OpenTalking frontend" "$run_dir/opentalking-web-$web_port.pid"
  stop_vite_port "$web_port"
else
  stop_pid_glob "OpenTalking frontend" "$run_dir/opentalking-web-*.pid"
  stop_vite_all
fi

stop_pid_file "OpenTalking API legacy pid" "$run_dir/opentalking-api.pid"
stop_pid_file "OpenTalking frontend legacy pid" "$run_dir/opentalking-web.pid"
stop_pid_file "OmniRT Wav2Lip" "$run_dir/omnirt-wav2lip.pid"
stop_pid_file "OmniRT FlashTalk endpoint" "$DIGITAL_HUMAN_HOME/omnirt/outputs/omnirt-flashtalk-ws.pid"
stop_pid_file "OmniRT FlashTalk avatar gateway" "$run_dir/omnirt-flashtalk.pid"
