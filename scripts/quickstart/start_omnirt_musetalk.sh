#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
default_home="$(cd -- "$repo_root/.." && pwd)"
# shellcheck disable=SC1091
source "$script_dir/_helpers.sh"

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
quickstart_source_env "$env_file"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/quickstart/start_omnirt_musetalk.sh [--device cuda|npu|cpu] [--port PORT] [--musetalk-port PORT] [--skip-install] [--no-update]

Examples:
  bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda --port 9001
  bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda --port 9001 --musetalk-port 8766 --skip-install
USAGE
}

device="${OMNIRT_MUSETALK_DEVICE:-cuda}"
port="${OMNIRT_PORT:-9000}"
host="${OMNIRT_HOST:-0.0.0.0}"
musetalk_port="${OMNIRT_MUSETALK_PORT:-8766}"
musetalk_host="${OMNIRT_MUSETALK_HOST:-127.0.0.1}"
install_deps=1
update_runtime=1

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
    --musetalk-port)
      musetalk_port="$2"
      shift 2
      ;;
    --musetalk-host)
      musetalk_host="$2"
      shift 2
      ;;
    --no-update)
      update_runtime=0
      shift
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
    ;;
  npu|ascend)
    runtime_device="npu"
    backend="ascend"
    ;;
  cpu)
    runtime_device="cpu"
    backend="cpu"
    ;;
  *)
    echo "Unsupported MuseTalk device: $device" >&2
    exit 2
    ;;
esac

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
export OMNIRT_REPO="${OMNIRT_REPO:-$DIGITAL_HUMAN_HOME/omnirt}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MUSETALK_MODEL_ROOT:-${OMNIRT_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}}"
export OMNIRT_HOME="${OMNIRT_HOME:-$OMNIRT_REPO/.omnirt}"
export TMPDIR="${TMPDIR:-$DIGITAL_HUMAN_HOME/tmp}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.cache/uv}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.cache/pip}"
export OPENTALKING_MUSETALK_MMCV_FIND_LINKS="${OPENTALKING_MUSETALK_MMCV_FIND_LINKS:-$DIGITAL_HUMAN_HOME/wheelhouse}"

omnirt_dir="$OMNIRT_REPO"
run_dir="$DIGITAL_HUMAN_HOME/run"
log_dir="$DIGITAL_HUMAN_HOME/logs"
gateway_pid_file="$run_dir/omnirt-musetalk.pid"
gateway_log_file="$log_dir/omnirt-musetalk-gateway.log"
backend_pid_file="$run_dir/omnirt-musetalk-ws.pid"
backend_log_file="$log_dir/omnirt-musetalk-ws.log"

mkdir -p "$run_dir" "$log_dir" "$TMPDIR" "$UV_CACHE_DIR" "$PIP_CACHE_DIR"

if [[ -f "$gateway_pid_file" ]]; then
  old_pid="$(cat "$gateway_pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "OmniRT MuseTalk gateway is already running: pid=$old_pid port=$port"
    echo "Log: $gateway_log_file"
    exit 0
  fi
  rm -f "$gateway_pid_file"
fi

if [[ -f "$backend_pid_file" ]]; then
  old_pid="$(cat "$backend_pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "OmniRT MuseTalk WS backend is already running: pid=$old_pid port=$musetalk_port"
    echo "Log: $backend_log_file"
  else
    rm -f "$backend_pid_file"
  fi
fi

if ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN; then
  echo "OmniRT gateway port $port is already in use." >&2
  ss -ltnp "sport = :$port" >&2 || true
  exit 1
fi
if ss -ltn "sport = :$musetalk_port" 2>/dev/null | grep -q LISTEN; then
  echo "MuseTalk WS backend port $musetalk_port is already in use." >&2
  ss -ltnp "sport = :$musetalk_port" >&2 || true
  exit 1
fi

if [[ ! -d "$omnirt_dir" ]]; then
  echo "Missing OmniRT checkout: $omnirt_dir" >&2
  exit 1
fi
if [[ ! -f "$omnirt_dir/.venv/bin/activate" ]]; then
  echo "Missing OmniRT virtualenv: $omnirt_dir/.venv" >&2
  echo "Run this first: cd \"$omnirt_dir\" && uv sync --extra server" >&2
  exit 1
fi

omnirt_cli() {
  if [[ -x "$omnirt_dir/.venv/bin/omnirt" ]]; then
    "$omnirt_dir/.venv/bin/omnirt" "$@"
  else
    PYTHONPATH="$omnirt_dir/src${PYTHONPATH:+:$PYTHONPATH}" "$omnirt_dir/.venv/bin/python" -m omnirt.cli.main "$@"
  fi
}

_musetalk_runtime_ld_library_path() {
  local py_bin="$1"
  local paths=()
  local site_dir
  site_dir="$("$py_bin" - <<'PY' 2>/dev/null || true
import site
paths = site.getsitepackages()
print(paths[0] if paths else "")
PY
)"
  if [[ -n "$site_dir" && -d "$site_dir/torch/lib" ]]; then
    paths+=("$site_dir/torch/lib")
  fi
  for candidate in \
    /usr/local/cuda/lib64 \
    /usr/local/cuda/extras/CUPTI/lib64 \
    /usr/local/cuda-11.8/lib64 \
    /usr/local/cuda-11.8/extras/CUPTI/lib64 \
    /usr/local/cuda-11.8/nsight-systems-2022.4.2/target-linux-x64 \
    /usr/local/cuda-11.7/lib64 \
    /usr/local/cuda-11.7/extras/CUPTI/lib64; do
    if [[ -d "$candidate" ]]; then
      paths+=("$candidate")
    fi
  done
  IFS=:
  printf '%s' "${paths[*]}"
}

ensure_musetalk_openmmlab() {
  local py_bin="$1"
  local extra_ld
  extra_ld="$(_musetalk_runtime_ld_library_path "$py_bin")"
  if LD_LIBRARY_PATH="${extra_ld}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$py_bin" - <<'PY' >/dev/null 2>&1
import importlib
for name in ("mmengine", "mmcv", "mmdet", "mmpose"):
    importlib.import_module(name)
PY
  then
    return 0
  fi

  echo "Installing MuseTalk OpenMMLab dependencies into runtime venv ..."
  "$py_bin" -m pip install -U openmim
  "$py_bin" -m pip install mmengine
  if [[ -d "$OPENTALKING_MUSETALK_MMCV_FIND_LINKS" ]] && compgen -G "$OPENTALKING_MUSETALK_MMCV_FIND_LINKS/mmcv-2.0.1-*.whl" >/dev/null; then
    "$py_bin" -m pip install --no-index --find-links "$OPENTALKING_MUSETALK_MMCV_FIND_LINKS" "mmcv==2.0.1"
  else
    "$py_bin" -m mim install "mmcv==2.0.1"
  fi
  "$py_bin" -m pip install --no-deps "mmdet==3.1.0"
  "$py_bin" -m pip install --no-deps "mmpose==1.1.0"
}

check_musetalk_runtime_deps() {
  local py_bin="$1"
  local extra_ld
  extra_ld="$(_musetalk_runtime_ld_library_path "$py_bin")"
  LD_LIBRARY_PATH="${extra_ld}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$py_bin" - <<'PY'
import importlib
missing = []
for name in ("torch", "torchvision", "torchaudio", "mmengine", "mmcv", "mmcv._ext", "mmdet", "mmpose"):
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name}: {type(exc).__name__}: {exc}")
if missing:
    raise SystemExit("MuseTalk runtime dependencies are incomplete:\n" + "\n".join(missing))
PY
}

test -f "$OMNIRT_MODEL_ROOT/musetalk/pytorch_model.bin" || { echo "Missing MuseTalk UNet weights" >&2; exit 1; }
test -f "$OMNIRT_MODEL_ROOT/musetalk/musetalk.json" || { echo "Missing MuseTalk UNet config" >&2; exit 1; }
test -f "$OMNIRT_MODEL_ROOT/whisper/tiny.pt" || { echo "Missing Whisper tiny checkpoint" >&2; exit 1; }
test -f "$OMNIRT_MODEL_ROOT/dwpose/dw-ll_ucoco_384.pth" || { echo "Missing DWPose checkpoint" >&2; exit 1; }
test -f "$OMNIRT_MODEL_ROOT/face-parse-bisenet/79999_iter.pth" || { echo "Missing face parsing checkpoint" >&2; exit 1; }

echo "Starting OmniRT MuseTalk"
echo "  omnirt:        $omnirt_dir"
echo "  omnirt home:   $OMNIRT_HOME"
echo "  models:        $OMNIRT_MODEL_ROOT"
echo "  device:        $runtime_device"
echo "  gateway:       http://127.0.0.1:$port"
echo "  backend ws:    ws://127.0.0.1:$musetalk_port"
echo "  gateway log:   $gateway_log_file"
echo "  backend log:   $backend_log_file"

(
  cd "$omnirt_dir"
  source .venv/bin/activate
  if [[ "$install_deps" == "1" ]]; then
    uv sync --extra server
    install_args=(runtime install musetalk --device "$runtime_device" --home "$OMNIRT_HOME")
    if [[ "$update_runtime" == "0" ]]; then
      install_args+=(--no-update)
    fi
    omnirt_cli "${install_args[@]}"
  fi
) >>"$backend_log_file" 2>&1

runtime_json="$(
  cd "$omnirt_dir"
  source .venv/bin/activate
  omnirt_cli runtime status musetalk --device "$runtime_device" --home "$OMNIRT_HOME" --json
)"
musetalk_repo="$(
  RUNTIME_JSON="$runtime_json" python3 - <<'PY'
import json
import os
data = json.loads(os.environ["RUNTIME_JSON"])
for item in data["checks"]:
    if item["name"] == "repo_path":
        print(item["path"])
        break
PY
)"
musetalk_python="$(
  cd "$omnirt_dir"
  source .venv/bin/activate
  omnirt_cli runtime env musetalk --device "$runtime_device" --home "$OMNIRT_HOME" --json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["OMNIRT_MUSETALK_PYTHON"])'
)"

if [[ ! -d "$musetalk_repo/musetalk" ]]; then
  echo "MuseTalk runtime source checkout is not ready: $musetalk_repo" >&2
  echo "See install log: $backend_log_file" >&2
  exit 1
fi

echo "  musetalk repo: $musetalk_repo"
echo "  python:        $musetalk_python"

if [[ "$install_deps" == "1" ]]; then
  ensure_musetalk_openmmlab "$musetalk_python" >>"$backend_log_file" 2>&1
fi
runtime_ld="$(_musetalk_runtime_ld_library_path "$musetalk_python")"
export LD_LIBRARY_PATH="${runtime_ld}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if ! check_musetalk_runtime_deps "$musetalk_python" >>"$backend_log_file" 2>&1; then
  echo "MuseTalk runtime dependencies are incomplete. Last log lines:" >&2
  tail -120 "$backend_log_file" >&2 || true
  exit 1
fi

(
  cd "$omnirt_dir"
  source .venv/bin/activate
  export OMNIRT_MUSETALK_REPO="$musetalk_repo"
  export OMNIRT_MUSETALK_PYTHON="$musetalk_python"
  export OMNIRT_MUSETALK_MODELS_DIR="$OMNIRT_MODEL_ROOT"
  export OMNIRT_MUSETALK_DEVICE="$runtime_device"
  export OMNIRT_MUSETALK_HOST="$musetalk_host"
  export OMNIRT_MUSETALK_PORT="$musetalk_port"
  export OMNIRT_MUSETALK_PRELOAD="${OMNIRT_MUSETALK_PRELOAD:-1}"
  export OMNIRT_MUSETALK_MAX_LONG_EDGE="${OMNIRT_MUSETALK_MAX_LONG_EDGE:-512}"
  export OMNIRT_MUSETALK_MIN_LONG_EDGE="${OMNIRT_MUSETALK_MIN_LONG_EDGE:-0}"
  export OMNIRT_MUSETALK_JPEG_QUALITY="${OMNIRT_MUSETALK_JPEG_QUALITY:-60}"
  export OMNIRT_MUSETALK_BATCH_SIZE="${OMNIRT_MUSETALK_BATCH_SIZE:-8}"
  export OMNIRT_MUSETALK_FPS="${OMNIRT_MUSETALK_FPS:-25}"
  export OMNIRT_MUSETALK_FRAME_NUM="${OMNIRT_MUSETALK_FRAME_NUM:-33}"
  export OMNIRT_MUSETALK_MOTION_FRAMES_NUM="${OMNIRT_MUSETALK_MOTION_FRAMES_NUM:-8}"
  export OMNIRT_MUSETALK_LOG_FILE="$backend_log_file"
  export OMNIRT_MUSETALK_PID_FILE="$backend_pid_file"
  export OMNIRT_MUSETALK_BACKGROUND=1
  bash scripts/start_musetalk_ws.sh --background
) >>"$backend_log_file" 2>&1

backend_pid="$(cat "$backend_pid_file" 2>/dev/null || true)"
if [[ -z "$backend_pid" ]] || ! kill -0 "$backend_pid" >/dev/null 2>&1; then
  echo "MuseTalk WS backend failed to start. Last log lines:" >&2
  tail -100 "$backend_log_file" >&2 || true
  rm -f "$backend_pid_file"
  exit 1
fi

for _ in {1..120}; do
  if ! kill -0 "$backend_pid" >/dev/null 2>&1; then
    echo "MuseTalk WS backend exited during startup. Last log lines:" >&2
    tail -100 "$backend_log_file" >&2 || true
    rm -f "$backend_pid_file"
    exit 1
  fi
  if ss -ltn "sport = :$musetalk_port" 2>/dev/null | grep -q LISTEN; then
    break
  fi
  sleep 1
done

if ! ss -ltn "sport = :$musetalk_port" 2>/dev/null | grep -q LISTEN; then
  echo "MuseTalk WS backend did not listen on port $musetalk_port. Last log lines:" >&2
  tail -100 "$backend_log_file" >&2 || true
  exit 1
fi

(
  cd "$omnirt_dir"
  source .venv/bin/activate
  export OMNIRT_AVATAR_MUSETALK_WS_URL="ws://127.0.0.1:$musetalk_port"
  if [[ -x "$omnirt_dir/.venv/bin/omnirt" ]]; then
    setsid "$omnirt_dir/.venv/bin/omnirt" serve-avatar-ws --host "$host" --port "$port" --backend "$backend" >"$gateway_log_file" 2>&1 < /dev/null &
  else
    export PYTHONPATH="$omnirt_dir/src${PYTHONPATH:+:$PYTHONPATH}"
    setsid "$omnirt_dir/.venv/bin/python" -m omnirt.cli.main serve-avatar-ws --host "$host" --port "$port" --backend "$backend" >"$gateway_log_file" 2>&1 < /dev/null &
  fi
  echo "$!" >"$gateway_pid_file"
)

gateway_pid="$(cat "$gateway_pid_file" 2>/dev/null || true)"
if [[ -z "$gateway_pid" ]]; then
  echo "Failed to capture OmniRT MuseTalk gateway pid." >&2
  exit 1
fi

for _ in {1..60}; do
  if ! kill -0 "$gateway_pid" >/dev/null 2>&1; then
    echo "OmniRT MuseTalk gateway exited during startup. Last log lines:" >&2
    tail -100 "$gateway_log_file" >&2 || true
    rm -f "$gateway_pid_file"
    exit 1
  fi
  if curl --max-time 2 -fsS "http://127.0.0.1:$port/v1/audio2video/models" | grep -q '"musetalk"'; then
    echo "OmniRT MuseTalk is up: http://127.0.0.1:$port"
    exit 0
  fi
  sleep 1
done

echo "OmniRT MuseTalk gateway did not report musetalk ready. Last log lines:" >&2
tail -100 "$gateway_log_file" >&2 || true
exit 1
