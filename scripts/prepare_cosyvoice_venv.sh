#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

venv_dir="${OPENTALKING_COSYVOICE_VENV_DIR:-$repo_root/.venv-cosyvoice}"
runtime_dir="${OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR:-$repo_root/models/local-audio/runtime/CosyVoice}"
requirements_file="${OPENTALKING_COSYVOICE_REQUIREMENTS:-$runtime_dir/requirements.txt}"

export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [[ ! -d "$runtime_dir" ]]; then
  echo "Missing CosyVoice runtime: $runtime_dir" >&2
  echo "Clone FunAudioLLM/CosyVoice there, or set OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR." >&2
  exit 1
fi

if [[ ! -f "$requirements_file" ]]; then
  echo "Missing CosyVoice requirements: $requirements_file" >&2
  exit 1
fi

resolve_bootstrap_python() {
  if [[ -n "${OPENTALKING_COSYVOICE_BOOTSTRAP_PYTHON:-}" ]]; then
    printf '%s\n' "$OPENTALKING_COSYVOICE_BOOTSTRAP_PYTHON"
    return 0
  fi
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
    return 0
  fi
  if command -v python3.11 >/dev/null 2>&1; then
    command -v python3.11
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    if uv python find 3.11 >/dev/null 2>&1; then
      uv python find 3.11
      return 0
    fi
    uv python install 3.11 >/dev/null
    uv python find 3.11
    return 0
  fi
  command -v python3
}

python_bin="$(resolve_bootstrap_python)"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  echo "Creating CosyVoice venv: $venv_dir"
  "$python_bin" -m venv "$venv_dir"
fi

venv_python="$venv_dir/bin/python"
tmp_dir="${OPENTALKING_COSYVOICE_TMPDIR:-$venv_dir/.tmp}"
pip_cache_dir="${OPENTALKING_COSYVOICE_PIP_CACHE_DIR:-$venv_dir/.pip-cache}"
mkdir -p "$tmp_dir" "$pip_cache_dir"
export TMPDIR="$tmp_dir"
export PIP_CACHE_DIR="$pip_cache_dir"
find "$tmp_dir" -mindepth 1 -maxdepth 1 -name 'pip-*' -exec rm -rf {} +

pip_install_initial() {
  "$venv_python" -m pip install \
    --retries "${OPENTALKING_COSYVOICE_PIP_RETRIES:-10}" \
    --timeout "${OPENTALKING_COSYVOICE_PIP_TIMEOUT:-120}" \
    "$@"
}

echo "Installing CosyVoice runtime dependencies"
pip_install_initial --upgrade "pip<26" "setuptools<81" wheel

pip_common_args=(
  --retries "${OPENTALKING_COSYVOICE_PIP_RETRIES:-10}"
  --timeout "${OPENTALKING_COSYVOICE_PIP_TIMEOUT:-120}"
)
if "$venv_python" -m pip install --help | grep -q -- '--resume-retries'; then
  pip_common_args+=(--resume-retries "${OPENTALKING_COSYVOICE_PIP_RESUME_RETRIES:-10}")
fi

pip_install() {
  "$venv_python" -m pip install "${pip_common_args[@]}" "$@"
}

pip_install "numpy==1.26.4" "Cython>=3.0"
filtered_requirements="$(mktemp)"
trap 'rm -f "$filtered_requirements"' EXIT
filter_pattern='^[[:space:]]*(openai-whisper|pyworld|torch|torchaudio)=='
if [[ "${OPENTALKING_COSYVOICE_INSTALL_TENSORRT:-0}" != "1" ]]; then
  filter_pattern='^[[:space:]]*(openai-whisper|pyworld|torch|torchaudio|tensorrt-cu12.*)=='
fi
grep -Ev "$filter_pattern" "$requirements_file" \
  | grep -Ev '^[[:space:]]*--extra-index-url[[:space:]]+https://download\.pytorch\.org/' \
  >"$filtered_requirements"
pip_install \
  "torch==2.3.1" \
  "torchaudio==2.3.1"
pip_install -r "$filtered_requirements"
pip_install --no-build-isolation "openai-whisper==20231117"
pip_install --no-build-isolation "pyworld==0.3.4"

echo "Installing OpenTalking sidecar service dependencies"
pip_install \
  "fastapi>=0.109" \
  "uvicorn[standard]>=0.27" \
  "pydantic>=2" \
  "numpy>=1.24,<2" \
  "soundfile>=0.12" \
  "transformers==4.51.3"

"$venv_python" - <<'PY'
import importlib.metadata as metadata

for package in ("transformers", "tokenizers", "torch", "torchaudio", "onnxruntime-gpu", "onnxruntime"):
    try:
        print(f"{package}={metadata.version(package)}")
    except metadata.PackageNotFoundError:
        print(f"{package}=missing")
PY

echo "CosyVoice venv is ready: $venv_dir"
