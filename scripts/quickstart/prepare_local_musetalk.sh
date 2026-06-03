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
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="${OPENTALKING_MUSETALK_PREPROCESS_PYTHON:-$repo_root/.venv/bin/python}"
export TMPDIR="${TMPDIR:-$DIGITAL_HUMAN_HOME/tmp}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.cache/pip}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.cache/uv}"
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR" "$UV_CACHE_DIR"

if [[ ! -f "$repo_root/.venv/bin/activate" ]]; then
  echo "Missing OpenTalking virtualenv: $repo_root/.venv" >&2
  echo "Run this first: cd \"$repo_root\" && uv sync --extra models --extra dev --python 3.11" >&2
  exit 1
fi

check_runtime() {
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
    "mmengine",
    "mmcv",
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

preprocess_python = Path(os.environ["OPENTALKING_MUSETALK_PREPROCESS_PYTHON"])
if not preprocess_python.exists():
    missing.append(str(preprocess_python))
else:
    import subprocess

    code = (
        "import mmcv, mmdet, mmpose, torch; "
        "print(torch.__version__)"
    )
    cp = subprocess.run(
        [str(preprocess_python), "-c", code],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if cp.returncode != 0:
        missing.append(
            "preprocess python lacks MuseTalk preprocessing dependencies: "
            + str(preprocess_python)
            + "\n"
            + cp.stderr.strip()
        )
if missing:
    raise SystemExit("Missing local MuseTalk runtime requirements:\n" + "\n".join(missing))
PY
}

if ! check_runtime >/dev/null 2>&1; then
  if [[ "$install_deps" != "1" ]]; then
    check_runtime
  fi
  (
    cd "$repo_root"
    source .venv/bin/activate
    python -m pip install "setuptools<81"
    python -m pip install -e ".[models]"
    python -m pip install json-tricks munkres pycocotools shapely terminaltables xtcocotools
    python -m pip install --no-build-isolation chumpy
    python -m mim install mmengine
    python -m pip install "mmcv-lite==2.0.1"
    python -m mim install "mmdet==3.1.0"
    python -m mim install "mmpose==1.1.0"
  )
fi

check_runtime
echo "OpenTalking local MuseTalk runtime dependencies are ready."
