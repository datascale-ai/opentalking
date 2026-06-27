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
  bash scripts/quickstart/prepare_local_musetalk.sh [--skip-install]

Prepare OpenTalking's in-process MuseTalk local runtime dependencies.
This does not install, start, or inspect OmniRT.
USAGE
}

install_deps=1
while [[ $# -gt 0 ]]; do
  case "$1" in
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

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_MUSETALK_MODEL_ROOT="${OPENTALKING_MUSETALK_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
export OPENTALKING_MUSETALK_REPO="${OPENTALKING_MUSETALK_REPO:-$DIGITAL_HUMAN_HOME/model-repos/MuseTalk}"
preprocess_root="${OPENTALKING_MUSETALK_PREPROCESS_ROOT:-$DIGITAL_HUMAN_HOME/runtimes/musetalk-preprocess}"
export OPENTALKING_MUSETALK_PREPROCESS_ROOT="$preprocess_root"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="${OPENTALKING_MUSETALK_PREPROCESS_PYTHON:-$preprocess_root/venv/bin/python}"
export TMPDIR="${TMPDIR:-$DIGITAL_HUMAN_HOME/tmp}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.cache/pip}"
export OPENTALKING_MUSETALK_MMCV_FIND_LINKS="${OPENTALKING_MUSETALK_MMCV_FIND_LINKS:-$DIGITAL_HUMAN_HOME/wheelhouse}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.cache/uv}"
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR" "$UV_CACHE_DIR" "$preprocess_root"

if [[ ! -f "$repo_root/.venv/bin/activate" ]]; then
  echo "Missing OpenTalking virtualenv: $repo_root/.venv" >&2
  echo "Run this first: cd \"$repo_root\" && uv sync --extra models --extra dev --python 3.11" >&2
  exit 1
fi

_musetalk_preprocess_ld_library_path() {
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

check_main_runtime() {
  "$repo_root/.venv/bin/python" - <<'PY'
import importlib
import os
from pathlib import Path

required = (
    "pkg_resources",
    "torch",
    "diffusers",
    "accelerate",
    "whisper",
    "cv2",
)
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name}: {type(exc).__name__}: {exc}")

models_dir = Path(os.environ["OPENTALKING_MUSETALK_MODEL_ROOT"])
required_files = (
    models_dir / "musetalk" / "pytorch_model.bin",
    models_dir / "musetalk" / "musetalk.json",
    models_dir / "sd-vae-ft-mse",
    models_dir / "whisper" / "tiny.pt",
    models_dir / "dwpose" / "dw-ll_ucoco_384.pth",
    models_dir / "face-parse-bisenet" / "79999_iter.pth",
)
missing.extend(str(path) for path in required_files if not path.exists())

musetalk_repo = Path(os.environ["OPENTALKING_MUSETALK_REPO"])
repo_files = (
    musetalk_repo / "musetalk" / "utils" / "preprocessing.py",
    musetalk_repo / "musetalk" / "utils" / "blending.py",
)
missing.extend(str(path) for path in repo_files if not path.exists())
if missing:
    raise SystemExit("Missing local MuseTalk runtime requirements:\n" + "\n".join(missing))
PY
}

check_preprocess_runtime() {
  local preprocess_python="$OPENTALKING_MUSETALK_PREPROCESS_PYTHON"
  if [[ ! -x "$preprocess_python" ]]; then
    echo "Missing MuseTalk preprocessing virtualenv: $preprocess_python" >&2
    return 1
  fi
  local extra_ld
  extra_ld="$(_musetalk_preprocess_ld_library_path "$preprocess_python")"
  LD_LIBRARY_PATH="${extra_ld}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$preprocess_python" - <<'PY'
import importlib
required = (
    "torch",
    "torchvision",
    "cv2",
    "mmengine",
    "mmcv",
    "mmcv._ext",
    "mmdet",
    "mmpose",
    "json_tricks",
    "munkres",
    "pycocotools",
    "shapely",
    "terminaltables",
    "xtcocotools",
)
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name}: {type(exc).__name__}: {exc}")
if missing:
    raise SystemExit("Missing MuseTalk official preprocessing requirements:\n" + "\n".join(missing))
PY
}

install_preprocess_runtime() {
  local venv_dir="$preprocess_root/venv"
  local py_bin="$venv_dir/bin/python"
  if [[ ! -x "$py_bin" ]]; then
    uv venv --seed --python 3.10 "$venv_dir"
  fi
  "$py_bin" -m pip install -U pip "setuptools<81" wheel openmim
  "$py_bin" -m pip install cmake lit sympy networkx jinja2 MarkupSafe
  "$py_bin" -m pip install --no-deps "torch==2.0.1+cu118" "torchvision==0.15.2+cu118" "torchaudio==2.0.2+cu118" \
    --extra-index-url https://download.pytorch.org/whl/cu118
  "$py_bin" -m pip install "numpy<2" opencv-python==4.9.0.80 pillow tqdm scipy soundfile requests imageio imageio-ffmpeg omegaconf ffmpeg-python
  "$py_bin" -m pip install json-tricks munkres pycocotools shapely terminaltables xtcocotools
  "$py_bin" -m pip install --no-build-isolation chumpy
  "$py_bin" -m pip install mmengine
  if [[ -d "$OPENTALKING_MUSETALK_MMCV_FIND_LINKS" ]] && compgen -G "$OPENTALKING_MUSETALK_MMCV_FIND_LINKS/mmcv-2.0.1-*.whl" >/dev/null; then
    "$py_bin" -m pip install --no-index --find-links "$OPENTALKING_MUSETALK_MMCV_FIND_LINKS" "mmcv==2.0.1"
  else
    "$py_bin" -m mim install "mmcv==2.0.1"
  fi
  "$py_bin" -m pip install --no-deps "mmdet==3.1.0"
  "$py_bin" -m pip install --no-deps "mmpose==1.1.0"
}

if ! check_main_runtime >/dev/null 2>&1; then
  if [[ "$install_deps" != "1" ]]; then
    check_main_runtime
  fi
  (
    cd "$repo_root"
    source .venv/bin/activate
    python -m pip install "setuptools<81"
    python -m pip install -e ".[models]"
  )
fi

if ! check_preprocess_runtime >/dev/null 2>&1; then
  if [[ "$install_deps" != "1" ]]; then
    check_preprocess_runtime
  fi
  install_preprocess_runtime
fi

check_main_runtime
check_preprocess_runtime
echo "OpenTalking local MuseTalk runtime dependencies are ready."
