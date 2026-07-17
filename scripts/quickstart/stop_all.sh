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
web_dir="$repo_root/apps/web"

summary_services=()
summary_targets=()
summary_results=()
summary_pids=()
summary_details=()

record_stop_result() {
  local service="$1"
  local target="$2"
  local result="$3"
  local pid="${4:-"-"}"
  local detail="${5:-"-"}"

  summary_services+=("$service")
  summary_targets+=("$target")
  summary_results+=("$result")
  summary_pids+=("${pid:-"-"}")
  summary_details+=("${detail:-"-"}")
}

print_stop_summary() {
  local count="${#summary_services[@]}"
  if [[ "$count" == "0" ]]; then
    return
  fi

  echo ""
  echo "Stop summary:"
  printf '+------------------------------------------------+--------------------------------+-------------+---------+--------------------------------+\n'
  printf '| %-46s | %-30s | %-11s | %-7s | %-30s |\n' "Service" "Target" "Result" "PID" "Detail"
  printf '+------------------------------------------------+--------------------------------+-------------+---------+--------------------------------+\n'

  local i
  for ((i = 0; i < count; i++)); do
    printf '| %-46.46s | %-30.30s | %-11.11s | %-7.7s | %-30.30s |\n' \
      "${summary_services[$i]}" \
      "${summary_targets[$i]}" \
      "${summary_results[$i]}" \
      "${summary_pids[$i]}" \
      "${summary_details[$i]}"
  done
  printf '+------------------------------------------------+--------------------------------+-------------+---------+--------------------------------+\n'
}

pid_is_running() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi
  [[ -d "/proc/$pid" ]]
}

stop_pid_file() {
  local name="$1"
  local pid_file="$2"
  local target
  target="$(basename "$pid_file")"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name: not started by quickstart scripts"
    record_stop_result "$name" "$target" "not_started" "-" "no pid file"
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! pid_is_running "$pid"; then
    echo "$name: stale pid file removed"
    rm -f "$pid_file"
    record_stop_result "$name" "$target" "stale" "${pid:-"-"}" "pid file removed"
    return
  fi

  echo "Stopping $name: pid=$pid"
  if ! kill "$pid" >/dev/null 2>&1; then
    echo "$name: failed to stop pid=$pid (permission denied or process owned by another user)"
    record_stop_result "$name" "$target" "permission" "$pid" "kill failed"
    return
  fi
  for _ in {1..20}; do
    if ! pid_is_running "$pid"; then
      rm -f "$pid_file"
      echo "$name: stopped"
      record_stop_result "$name" "$target" "stopped" "$pid" "SIGTERM"
      return
    fi
    sleep 0.5
  done

  echo "$name: still running, sending SIGKILL"
  if ! kill -9 "$pid" >/dev/null 2>&1; then
    record_stop_result "$name" "$target" "residue" "$pid" "SIGKILL failed"
    return
  fi
  rm -f "$pid_file"
  record_stop_result "$name" "$target" "killed" "$pid" "SIGKILL"
}

stop_process_pid() {
  local name="$1"
  local target="$2"
  local pid="$3"
  if [[ -z "$pid" ]] || [[ "$pid" == "$$" ]]; then
    return
  fi
  if ! pid_is_running "$pid"; then
    return
  fi

  echo "Stopping $name: pid=$pid"
  if ! kill "$pid" >/dev/null 2>&1; then
    echo "$name: failed to stop pid=$pid (permission denied or process owned by another user)"
    record_stop_result "$name" "$target" "permission" "$pid" "kill failed"
    return
  fi

  for _ in {1..20}; do
    if ! pid_is_running "$pid"; then
      record_stop_result "$name" "$target" "stopped" "$pid" "SIGTERM"
      return
    fi
    sleep 0.5
  done

  echo "$name: still running, sending SIGKILL"
  if ! kill -9 "$pid" >/dev/null 2>&1; then
    record_stop_result "$name" "$target" "residue" "$pid" "SIGKILL failed"
    return
  fi
  record_stop_result "$name" "$target" "killed" "$pid" "SIGKILL"
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
    record_stop_result "$name" "$(basename "$pattern")" "not_started" "-" "no pid files"
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
    local env_text
    env_text="$(cat "/proc/$pid/environ" 2>/dev/null | tr '\0' '\n' || true)"
    if printf '%s\n' "$env_text" | grep -qx "OPENTALKING_UNIFIED_PORT=$port"; then
      stop_process_pid "OpenTalking API unified residue" "port $port" "$pid"
    elif [[ -z "$env_text" ]]; then
      stop_process_pid "OpenTalking API unified residue" "cmdline; env unreadable" "$pid"
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
    local cwd
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ "$cwd" == "$repo_root" ]] || [[ -z "$cwd" ]]; then
      stop_process_pid "OpenTalking API unified residue" "repo cwd" "$pid"
    fi
  done
}

stop_vite_port() {
  local port="$1"
  local pids
  pids="$(pgrep -f "vite .*--port $port" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  for pid in $pids; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    local cwd
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ -n "$cwd" ]] && [[ "$cwd" != "$web_dir" ]]; then
      continue
    fi
    stop_process_pid "OpenTalking frontend Vite residue" "port $port" "$pid"
  done
}

stop_vite_all() {
  local pids
  pids="$(pgrep -f "vite .*--port" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  for pid in $pids; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    local cwd
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ "$cwd" != "$web_dir" ]]; then
      continue
    fi
    stop_process_pid "OpenTalking frontend Vite residue" "repo web" "$pid"
  done
}

stop_repo_cmdline_residue() {
  local name="$1"
  local pattern="$2"
  local target="$3"
  local pids
  pids="$(pgrep -f "$pattern" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi
  for pid in $pids; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    local cwd
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ -n "$cwd" ]] && [[ "$cwd" != "$repo_root" ]]; then
      continue
    fi
    stop_process_pid "$name" "$target" "$pid"
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
stop_pid_glob "Local CosyVoice" "$run_dir/local-cosyvoice-*.pid"
stop_pid_glob "Local F5-TTS" "$run_dir/local-f5-tts-*.pid"
stop_pid_glob "Local IndexTTS" "$run_dir/local-indextts-*.pid"
stop_repo_cmdline_residue "Local CosyVoice residue" "local_cosyvoice_service.py .*--port" "repo cwd"
stop_repo_cmdline_residue "Local F5-TTS residue" "local_f5_tts_service.py .*--port" "repo cwd"
stop_pid_file "OmniRT Wav2Lip" "$run_dir/omnirt-wav2lip.pid"
stop_pid_file "OmniRT QuickTalk" "$run_dir/omnirt-quicktalk.pid"
stop_pid_file "OmniRT FlashTalk endpoint" "$DIGITAL_HUMAN_HOME/omnirt/outputs/omnirt-flashtalk-ws.pid"
stop_pid_file "OmniRT FlashTalk avatar gateway" "$run_dir/omnirt-flashtalk.pid"
stop_pid_file "OmniRT MuseTalk WS backend" "$run_dir/omnirt-musetalk-ws.pid"
stop_pid_file "OmniRT MuseTalk gateway" "$run_dir/omnirt-musetalk.pid"

print_stop_summary
