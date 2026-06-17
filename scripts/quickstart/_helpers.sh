#!/usr/bin/env bash

quickstart_resolve_uv() {
  local candidate=""

  if candidate="$(command -v uv 2>/dev/null)"; then
    printf '%s\n' "$candidate"
    return 0
  fi

  for candidate in \
    "/snap/bin/uv" \
    "$HOME/.local/bin/uv" \
    "$HOME/bin/uv" \
    "/usr/local/bin/uv" \
    "/opt/homebrew/bin/uv"
  do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

quickstart_require_uv() {
  local purpose="${1:-this command}"
  local uv_bin=""

  if uv_bin="$(quickstart_resolve_uv)"; then
    printf '%s\n' "$uv_bin"
    return 0
  fi

  echo "Unable to find uv for $purpose." >&2
  echo "Install uv or add it to PATH, then retry." >&2
  return 1
}

quickstart_configure_uv_default_index() {
  if [[ -z "${UV_DEFAULT_INDEX:-}" && -z "${UV_INDEX_URL:-}" ]]; then
    export UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
  fi
}

quickstart_describe_uv_default_index() {
  printf '%s\n' "${UV_DEFAULT_INDEX:-${UV_INDEX_URL:-default}}"
}

quickstart_configure_utf8() {
  local locale_name="${OPENTALKING_QUICKSTART_LOCALE:-}"

  if [[ -z "$locale_name" ]]; then
    if locale -a 2>/dev/null | grep -Eiq '^(C|c)\.(UTF-8|utf8)$'; then
      locale_name="C.UTF-8"
    else
      locale_name="en_US.UTF-8"
    fi
  fi

  export LANG="$locale_name"
  export LC_ALL="$locale_name"
  export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
  export PYTHONUTF8="${PYTHONUTF8:-1}"
  export TERM="${OPENTALKING_QUICKSTART_TERM:-dumb}"
  export NO_COLOR="${NO_COLOR:-1}"
  export CLICOLOR="${CLICOLOR:-0}"
  export FORCE_COLOR="${FORCE_COLOR:-0}"
  export PY_COLORS="${PY_COLORS:-0}"
  export TQDM_DISABLE="${TQDM_DISABLE:-1}"
  export HF_HUB_DISABLE_PROGRESS_BARS="${HF_HUB_DISABLE_PROGRESS_BARS:-1}"
}

quickstart_source_env() {
  local env_file="$1"
  local restore_allexport=1
  local previous_exports=""
  local status=0

  if [[ ! -f "$env_file" ]]; then
    return 0
  fi

  previous_exports="$(export -p | sed 's/^declare -x /export /')"

  case "$-" in
    *a*) restore_allexport=0 ;;
  esac

  set -a
  # shellcheck disable=SC1090
  source "$env_file" || status=$?
  if [[ "$restore_allexport" == "1" ]]; then
    set +a
  fi
  eval "$previous_exports"
  return "$status"
}

quickstart_source_ascend_env() {
  local env_file="$1"
  local restore_nounset=1
  local status=0

  case "$-" in
    *u*) restore_nounset=0 ;;
  esac

  set +u
  # Ascend's set_env.sh may append to unset variables like LD_LIBRARY_PATH.
  # shellcheck disable=SC1090
  source "$env_file" || status=$?
  if [[ "$restore_nounset" == "0" ]]; then
    set -u
  fi
  return "$status"
}

quickstart_port_in_use() {
  local port="$1"

  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN
    return $?
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | grep -E "[\.:]$port[[:space:]].*(LISTEN|LISTENING)" >/dev/null
    return $?
  fi

  return 1
}

quickstart_describe_port() {
  local port="$1"

  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :$port" 2>/dev/null || true
    return 0
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN || true
    return 0
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat -anv 2>/dev/null | grep -E "[\.:]$port[[:space:]].*(LISTEN|LISTENING)" || true
    return 0
  fi

  return 1
}

quickstart_resolve_ffmpeg() {
  local py_bin="${repo_root:-}/.venv/bin/python"

  if [[ -n "${OPENTALKING_FFMPEG_BIN:-}" ]]; then
    printf '%s\n' "$OPENTALKING_FFMPEG_BIN"
    return 0
  fi

  if command -v ffmpeg >/dev/null 2>&1; then
    command -v ffmpeg
    return 0
  fi

  if [[ ! -x "$py_bin" ]]; then
    py_bin="python3"
  fi
  "$py_bin" - <<'PY'
import imageio_ffmpeg

print(imageio_ffmpeg.get_ffmpeg_exe())
PY
}

quickstart_detach() {
  local log_file="$1"
  shift

  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" >"$log_file" 2>&1 < /dev/null &
    printf '%s\n' "$!"
    return 0
  fi

  python3 - "$log_file" "$@" <<'PY'
import subprocess
import sys

log_file = sys.argv[1]
argv = sys.argv[2:]
with open(log_file, "ab", buffering=0) as log:
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        close_fds=True,
        start_new_session=True,
    )
print(process.pid)
PY
}
