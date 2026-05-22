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
  bash scripts/quickstart/start_omnirt_flashtalk.sh [--device cuda|npu] [--port PORT] [--flashtalk-port PORT] [--nproc N] [--skip-install]

Examples:
  bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu
  bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
USAGE
}

device="${OMNIRT_FLASHTALK_DEVICE:-npu}"
port="${OMNIRT_PORT:-9000}"
host="${OMNIRT_HOST:-0.0.0.0}"
flashtalk_port="${OMNIRT_FLASHTALK_PORT:-18766}"
nproc="${OMNIRT_FLASHTALK_NPROC_PER_NODE:-}"
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
    --flashtalk-port)
      flashtalk_port="$2"
      shift 2
      ;;
    --nproc)
      nproc="$2"
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
    backend="cuda"
    nproc="${nproc:-1}"
    ;;
  npu|ascend)
    backend="ascend"
    nproc="${nproc:-8}"
    ;;
  *)
    echo "Unsupported FlashTalk device: $device" >&2
    exit 2
    ;;
esac

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"

omnirt_dir="$DIGITAL_HUMAN_HOME/omnirt"
run_dir="$DIGITAL_HUMAN_HOME/run"
log_dir="$DIGITAL_HUMAN_HOME/logs"
pid_file="$run_dir/omnirt-flashtalk.pid"
log_file="$log_dir/omnirt-flashtalk.log"

mkdir -p "$run_dir" "$log_dir"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "OmniRT FlashTalk is already running: pid=$old_pid port=$port"
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

ckpt_dir="$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B"
wav2vec_dir="$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base"
repo_path="${OMNIRT_FLASHTALK_REPO_PATH:-$OMNIRT_MODEL_ROOT/SoulX-FlashTalk}"

test -d "$ckpt_dir" || { echo "Missing FlashTalk checkpoint directory: $ckpt_dir" >&2; exit 1; }
test -d "$wav2vec_dir" || { echo "Missing wav2vec directory: $wav2vec_dir" >&2; exit 1; }

if [[ "$backend" == "ascend" ]]; then
  ascend_env="${ASCEND_SET_ENV:-/usr/local/Ascend/ascend-toolkit/set_env.sh}"
  test -f "$ascend_env" || { echo "Missing Ascend set_env.sh: $ascend_env" >&2; exit 1; }
fi

echo "Starting OmniRT FlashTalk"
echo "  omnirt:         $omnirt_dir"
echo "  models:         $OMNIRT_MODEL_ROOT"
echo "  backend:        $backend"
echo "  port:           $port"
echo "  flashtalk port: $flashtalk_port"
echo "  nproc:          $nproc"
echo "  log:            $log_file"

(
  cd "$omnirt_dir"
  if [[ "$backend" == "ascend" ]]; then
    quickstart_source_ascend_env "${ASCEND_SET_ENV:-/usr/local/Ascend/ascend-toolkit/set_env.sh}"
  fi
  source .venv/bin/activate

  export OMNIRT_MODEL_ROOT="$OMNIRT_MODEL_ROOT"
  export OMNIRT_FLASHTALK_REPO_PATH="$repo_path"
  export OMNIRT_FLASHTALK_CKPT_DIR="$ckpt_dir"
  export OMNIRT_FLASHTALK_WAV2VEC_DIR="$wav2vec_dir"
  export OMNIRT_FLASHTALK_PORT="$flashtalk_port"
  export OMNIRT_FLASHTALK_NPROC_PER_NODE="$nproc"

  # OmniRT FlashTalk 渲染参数：传递给 omnirt/scripts/start_flashtalk_ws.sh
  # 如果 env 文件中未设置，使用与 opentalking/.env 一致的默认值
  export FLASHTALK_HEIGHT="${FLASHTALK_HEIGHT:-704}"
  export FLASHTALK_WIDTH="${FLASHTALK_WIDTH:-416}"
  export FLASHTALK_FRAME_NUM="${FLASHTALK_FRAME_NUM:-25}"
  export FLASHTALK_MOTION_FRAMES_NUM="${FLASHTALK_MOTION_FRAMES_NUM:-1}"
  export FLASHTALK_TGT_FPS="${FLASHTALK_TGT_FPS:-25}"
  export FLASHTALK_SAMPLE_STEPS="${FLASHTALK_SAMPLE_STEPS:-2}"
  export FLASHTALK_JPEG_QUALITY="${FLASHTALK_JPEG_QUALITY:-50}"
  export FLASHTALK_JPEG_WORKERS="${FLASHTALK_JPEG_WORKERS:-4}"

  echo "  FLASHTALK_FRAME_NUM=${FLASHTALK_FRAME_NUM:-<unset>}"
  echo "  FLASHTALK_MOTION_FRAMES_NUM=${FLASHTALK_MOTION_FRAMES_NUM:-<unset>}"
  echo "  FLASHTALK_HEIGHT=${FLASHTALK_HEIGHT:-<unset>}"
  echo "  FLASHTALK_WIDTH=${FLASHTALK_WIDTH:-<unset>}"
  echo "  FLASHTALK_SAMPLE_STEPS=${FLASHTALK_SAMPLE_STEPS:-<unset>}"
  echo "  FLASHTALK_TGT_FPS=${FLASHTALK_TGT_FPS:-<unset>}"
  echo "  FLASHTALK_JPEG_QUALITY=${FLASHTALK_JPEG_QUALITY:-<unset>}"
  echo "  FLASHTALK_JPEG_WORKERS=${FLASHTALK_JPEG_WORKERS:-<unset>}"

  if [[ "$install_deps" == "1" ]]; then
    uv_bin="$(quickstart_require_uv "OmniRT dependency installation")"
    if [[ "$backend" == "ascend" ]]; then
      python -m omnirt.cli.main runtime install flashtalk \
        --device ascend \
        --ckpt-dir "$ckpt_dir" \
        --wav2vec-dir "$wav2vec_dir"
    else
      if [[ ! -d "$OMNIRT_FLASHTALK_REPO_PATH/flash_talk" ]]; then
        git clone https://github.com/Soul-AILab/SoulX-FlashTalk.git "$OMNIRT_FLASHTALK_REPO_PATH"
      fi
      "$uv_bin" pip install -r "$OMNIRT_FLASHTALK_REPO_PATH/requirements.txt"
      "$uv_bin" pip install ninja
      "$uv_bin" pip install flash-attn --no-build-isolation
    fi
  fi

  bash scripts/start_flashtalk_ws.sh --background
  export OMNIRT_AVATAR_FLASHTALK_WS_URL="ws://127.0.0.1:$flashtalk_port"

  exec omnirt serve-avatar-ws --host "$host" --port "$port" --backend "$backend"
) >"$log_file" 2>&1 &

pid="$!"
echo "$pid" > "$pid_file"

for _ in {1..180}; do
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "OmniRT FlashTalk exited during startup. Last log lines:" >&2
    tail -120 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  if curl --max-time 2 -fsS "http://127.0.0.1:$port/v1/audio2video/models" >/dev/null 2>&1; then
    echo "OmniRT FlashTalk endpoint is up: http://127.0.0.1:$port"
    exit 0
  fi
  sleep 1
done

echo "OmniRT FlashTalk did not become ready in 180s. Last log lines:" >&2
tail -120 "$log_file" >&2 || true
exit 1
