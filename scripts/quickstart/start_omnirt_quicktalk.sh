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
  bash scripts/quickstart/start_omnirt_quicktalk.sh [--device cuda] [--port PORT] [--skip-install]

Examples:
  bash scripts/quickstart/start_omnirt_quicktalk.sh --device cuda
  OMNIRT_QUICKTALK_DEVICE=cuda:0 OMNIRT_QUICKTALK_HUBERT_DEVICE=cuda:1 bash scripts/quickstart/start_omnirt_quicktalk.sh
USAGE
}

device="${OMNIRT_QUICKTALK_DEVICE:-cuda:0}"
hubert_device="${OMNIRT_QUICKTALK_HUBERT_DEVICE:-$device}"
port="${OMNIRT_PORT:-9000}"
host="${OMNIRT_HOST:-0.0.0.0}"
install_deps=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      device="$2"
      hubert_device="${OMNIRT_QUICKTALK_HUBERT_DEVICE:-$device}"
      shift 2
      ;;
    --hubert-device)
      hubert_device="$2"
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
  cuda|cuda:*|gpu)
    backend="cuda"
    if [[ "$device" == "gpu" ]]; then
      device="cuda:0"
    fi
    ;;
  *)
    echo "QuickTalk currently supports CUDA devices only, got: $device" >&2
    exit 2
    ;;
esac

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
export OPENTALKING_MODEL_REPO_ROOT="${OPENTALKING_MODEL_REPO_ROOT:-$DIGITAL_HUMAN_HOME/model-repos}"
export OMNIRT_REPO="${OMNIRT_REPO:-$OPENTALKING_MODEL_REPO_ROOT/omnirt}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
quickstart_configure_uv_default_index

omnirt_dir="$OMNIRT_REPO"
run_dir="$DIGITAL_HUMAN_HOME/run"
log_dir="$DIGITAL_HUMAN_HOME/logs"
pid_file="$run_dir/omnirt-quicktalk.pid"
log_file="$log_dir/omnirt-quicktalk.log"
quicktalk_root="${OMNIRT_QUICKTALK_MODEL_ROOT:-$OMNIRT_MODEL_ROOT/quicktalk}"
checkpoint="${OMNIRT_QUICKTALK_CHECKPOINT:-$quicktalk_root/quicktalk.pth}"

mkdir -p "$run_dir" "$log_dir"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "OmniRT QuickTalk is already running: pid=$old_pid port=$port"
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

test -f "$checkpoint" || { echo "Missing QuickTalk checkpoint: $checkpoint" >&2; exit 1; }
test -f "$quicktalk_root/repair.npy" || { echo "Missing QuickTalk repair.npy: $quicktalk_root/repair.npy" >&2; exit 1; }
test -d "$quicktalk_root/chinese-hubert-large" || { echo "Missing HuBERT directory: $quicktalk_root/chinese-hubert-large" >&2; exit 1; }
test -d "$quicktalk_root/auxiliary/models/buffalo_l" || { echo "Missing InsightFace buffalo_l directory: $quicktalk_root/auxiliary/models/buffalo_l" >&2; exit 1; }

{
  echo "Starting OmniRT QuickTalk"
  echo "  omnirt:        $omnirt_dir"
  echo "  model root:    $quicktalk_root"
  echo "  checkpoint:    $checkpoint"
  echo "  device:        $device"
  echo "  hubert device: $hubert_device"
  echo "  max edge:      ${OMNIRT_QUICKTALK_MAX_LONG_EDGE:-900}"
  echo "  template sec:  ${OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS:-1}"
  echo "  uv index:      $(quickstart_describe_uv_default_index)"
  echo "  port:          $port"
  echo "  log:           $log_file"
}

uv_bin=""
if [[ "$install_deps" == "1" ]]; then
  uv_bin="$(quickstart_require_uv "OmniRT QuickTalk dependency installation")"
fi

pid="$(
  quickstart_detach "$log_file" bash -c '
set -euo pipefail

omnirt_dir="$1"
install_deps="$2"
uv_bin="$3"
omnirt_model_root="$4"
quicktalk_root="$5"
checkpoint="$6"
device="$7"
hubert_device="$8"
max_long_edge="$9"
max_template_seconds="${10}"
scale_h="${11}"
scale_w="${12}"
resolution="${13}"
neck_fade_start="${14}"
neck_fade_end="${15}"
allowed_frame_roots="${16}"
host="${17}"
port="${18}"
backend="${19}"

echo "[$(date -Is)] Starting OmniRT QuickTalk"
echo "  omnirt:        $omnirt_dir"
echo "  model root:    $quicktalk_root"
echo "  checkpoint:    $checkpoint"
echo "  device:        $device"
echo "  hubert device: $hubert_device"
echo "  max edge:      $max_long_edge"
echo "  template sec:  $max_template_seconds"
echo "  uv index:      ${UV_DEFAULT_INDEX:-${UV_INDEX_URL:-default}}"
echo "  port:          $port"
echo "  backend:       $backend"

cd "$omnirt_dir"
source .venv/bin/activate

if [[ "$install_deps" == "1" ]]; then
  "$uv_bin" sync --extra server --extra quicktalk-cuda --python 3.11
fi

export OMNIRT_MODEL_ROOT="$omnirt_model_root"
export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_MODEL_ROOT="$quicktalk_root"
export OMNIRT_QUICKTALK_CHECKPOINT="$checkpoint"
export OMNIRT_QUICKTALK_DEVICE="$device"
export OMNIRT_QUICKTALK_HUBERT_DEVICE="$hubert_device"
export OMNIRT_QUICKTALK_MAX_LONG_EDGE="$max_long_edge"
export OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS="$max_template_seconds"
export OMNIRT_QUICKTALK_SCALE_H="$scale_h"
export OMNIRT_QUICKTALK_SCALE_W="$scale_w"
export OMNIRT_QUICKTALK_RESOLUTION="$resolution"
export OMNIRT_QUICKTALK_NECK_FADE_START="$neck_fade_start"
export OMNIRT_QUICKTALK_NECK_FADE_END="$neck_fade_end"
export OMNIRT_ALLOWED_FRAME_ROOTS="$allowed_frame_roots"

exec omnirt serve-avatar-ws --host "$host" --port "$port" --backend "$backend"
' bash \
    "$omnirt_dir" \
    "$install_deps" \
    "$uv_bin" \
    "$OMNIRT_MODEL_ROOT" \
    "$quicktalk_root" \
    "$checkpoint" \
    "$device" \
    "$hubert_device" \
    "${OMNIRT_QUICKTALK_MAX_LONG_EDGE:-900}" \
    "${OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS:-1}" \
    "${OMNIRT_QUICKTALK_SCALE_H:-1.6}" \
    "${OMNIRT_QUICKTALK_SCALE_W:-3.6}" \
    "${OMNIRT_QUICKTALK_RESOLUTION:-256}" \
    "${OMNIRT_QUICKTALK_NECK_FADE_START:-0.72}" \
    "${OMNIRT_QUICKTALK_NECK_FADE_END:-0.88}" \
    "${OMNIRT_ALLOWED_FRAME_ROOTS:-$DIGITAL_HUMAN_HOME/opentalking/examples/avatars}" \
    "$host" \
    "$port" \
    "$backend"
)"
echo "$pid" > "$pid_file"

for _ in {1..180}; do
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "OmniRT QuickTalk exited during startup. Last log lines:" >&2
    tail -120 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  if curl --max-time 2 -fsS "http://127.0.0.1:$port/v1/audio2video/models" >/dev/null 2>&1; then
    echo "OmniRT QuickTalk is up: http://127.0.0.1:$port"
    exit 0
  fi
  sleep 1
done

echo "OmniRT QuickTalk did not become ready in 180s. Last log lines:" >&2
tail -120 "$log_file" >&2 || true
exit 1
