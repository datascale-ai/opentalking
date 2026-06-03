#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
default_home="$(cd -- "$repo_root/.." && pwd)"
# shellcheck disable=SC1091
source "$script_dir/_helpers.sh"

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
if [[ -f "$env_file" ]]; then
  # shellcheck disable=SC1090
  source "$env_file"
fi

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/quickstart/start_omnirt_wav2lip.sh [--device cuda|npu] [--port PORT] [--skip-install]

Examples:
  bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
  bash scripts/quickstart/start_omnirt_wav2lip.sh --device npu
USAGE
}

device="${OMNIRT_WAV2LIP_DEVICE:-cuda}"
port="${OMNIRT_PORT:-9000}"
host="${OMNIRT_HOST:-0.0.0.0}"
install_deps=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      device="$2"
      shift 2
      ;;
    --port)
      port="$2"
      shift 2
      ;;
    --host)
      host="$2"
      shift 2
      ;;
    --skip-install)
      install_deps=0
      shift
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

case "$device" in
  cuda|gpu)
    runtime_device="cuda"
    backend="cuda"
    batch_size="${OMNIRT_WAV2LIP_BATCH_SIZE:-16}"
    ;;
  npu|ascend)
    runtime_device="npu"
    backend="ascend"
    batch_size="${OMNIRT_WAV2LIP_BATCH_SIZE:-8}"
    ;;
  *)
    echo "Unsupported Wav2Lip device: $device" >&2
    exit 2
    ;;
esac

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
export OMNIRT_REPO="${OMNIRT_REPO:-$DIGITAL_HUMAN_HOME/omnirt}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
quickstart_configure_uv_default_index

omnirt_dir="$OMNIRT_REPO"
run_dir="$DIGITAL_HUMAN_HOME/run"
log_dir="$DIGITAL_HUMAN_HOME/logs"
pid_file="$run_dir/omnirt-wav2lip.pid"
log_file="$log_dir/omnirt-wav2lip.log"

mkdir -p "$run_dir" "$log_dir"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "OmniRT Wav2Lip is already running: pid=$old_pid port=$port"
    echo "Log: $log_file"
    exit 0
  fi
  rm -f "$pid_file"
fi

if [[ ! -d "$omnirt_dir" ]]; then
  echo "Missing OmniRT checkout: $omnirt_dir" >&2
  exit 1
fi
if [[ ! -f "$omnirt_dir/.venv/bin/activate" ]]; then
  echo "Missing OmniRT virtualenv: $omnirt_dir/.venv" >&2
  if uv_bin="$(quickstart_resolve_uv)"; then
    echo "Run this first: cd \"$omnirt_dir\" && \"$uv_bin\" sync --extra server --python 3.11" >&2
  else
    echo "Install uv first, then run: cd \"$omnirt_dir\" && uv sync --extra server --python 3.11" >&2
  fi
  exit 1
fi

checkpoint="$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
s3fd="$OMNIRT_MODEL_ROOT/wav2lip/s3fd.pth"
test -f "$checkpoint" || { echo "Missing Wav2Lip checkpoint: $checkpoint" >&2; exit 1; }
test -f "$s3fd" || { echo "Missing S3FD checkpoint: $s3fd" >&2; exit 1; }

if [[ "$backend" == "ascend" ]]; then
  ascend_env="${ASCEND_SET_ENV:-/usr/local/Ascend/ascend-toolkit/set_env.sh}"
  test -f "$ascend_env" || { echo "Missing Ascend set_env.sh: $ascend_env" >&2; exit 1; }
fi

echo "Starting OmniRT Wav2Lip"
echo "  omnirt:  $omnirt_dir"
echo "  models:  $OMNIRT_MODEL_ROOT"
echo "  device:  $runtime_device"
echo "  backend: $backend"
echo "  port:    $port"
echo "  log:     $log_file"

(
  cd "$omnirt_dir"
  if [[ "$backend" == "ascend" ]]; then
    quickstart_source_ascend_env "${ASCEND_SET_ENV:-/usr/local/Ascend/ascend-toolkit/set_env.sh}"
  fi
  source .venv/bin/activate

  if [[ "$install_deps" == "1" ]]; then
    uv_bin="$(quickstart_require_uv "OmniRT dependency installation")"
    if [[ "$backend" == "cuda" ]]; then
      if grep -Eq '^[[:space:]]*wav2lip-cuda[[:space:]]*=' "$omnirt_dir/pyproject.toml"; then
        "$uv_bin" sync --extra server --extra wav2lip-cuda --python 3.11
      else
        echo "OmniRT extra 'wav2lip-cuda' is not defined; falling back to requirements-wav2lip.txt"
        "$uv_bin" sync --extra server --python 3.11
        "$uv_bin" pip install -r model_backends/wav2lip/requirements-wav2lip.txt
      fi
    else
      "$uv_bin" pip install -r model_backends/wav2lip/requirements-wav2lip-ascend.txt
    fi
  fi

  export OMNIRT_MODEL_ROOT="$OMNIRT_MODEL_ROOT"
  export OMNIRT_WAV2LIP_RUNTIME=1
  export OMNIRT_WAV2LIP_MODELS_DIR="$OMNIRT_MODEL_ROOT"
  export OMNIRT_WAV2LIP_CHECKPOINT="$checkpoint"
  export OMNIRT_WAV2LIP_DEVICE="$runtime_device"
  export OMNIRT_WAV2LIP_FACE_DET_DEVICE="${OMNIRT_WAV2LIP_FACE_DET_DEVICE:-cpu}"
  export OMNIRT_WAV2LIP_NPU_INDEX="${OMNIRT_WAV2LIP_NPU_INDEX:-0}"
  export OMNIRT_WAV2LIP_PRELOAD="${OMNIRT_WAV2LIP_PRELOAD:-1}"
  export OMNIRT_WAV2LIP_CPU_THREADS="${OMNIRT_WAV2LIP_CPU_THREADS:-4}"
  export OMNIRT_WAV2LIP_BATCH_SIZE="$batch_size"
  export OMNIRT_WAV2LIP_MAX_LONG_EDGE="${OMNIRT_WAV2LIP_MAX_LONG_EDGE:-832}"
  export OMNIRT_ALLOWED_FRAME_ROOTS="${OMNIRT_ALLOWED_FRAME_ROOTS:-$DIGITAL_HUMAN_HOME/opentalking/examples/avatars}"

  exec omnirt serve-avatar-ws --host "$host" --port "$port" --backend "$backend"
) >"$log_file" 2>&1 &

pid="$!"
echo "$pid" > "$pid_file"

for _ in {1..120}; do
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "OmniRT Wav2Lip exited during startup. Last log lines:" >&2
    tail -100 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  if curl --max-time 2 -fsS "http://127.0.0.1:$port/v1/audio2video/models" >/dev/null 2>&1; then
    echo "OmniRT Wav2Lip is up: http://127.0.0.1:$port"
    exit 0
  fi
  sleep 1
done

echo "OmniRT Wav2Lip did not become ready in 120s. Last log lines:" >&2
tail -100 "$log_file" >&2 || true
exit 1
