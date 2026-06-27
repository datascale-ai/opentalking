#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
default_home="$(cd -- "$repo_root/.." && pwd)"
quickstart_dir="$script_dir/quickstart"
# shellcheck disable=SC1091
source "$quickstart_dir/_helpers.sh"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/deploy_ascend_910b.sh [--port PORT] [--skip-install]

This wrapper validates the Ascend host environment and then delegates to:
  bash scripts/quickstart/start_omnirt_wav2lip.sh --device npu
USAGE
}

forward_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    *)
      forward_args+=("$1")
      shift
      ;;
  esac
done

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OMNIRT_WAV2LIP_DEVICE="${OMNIRT_WAV2LIP_DEVICE:-npu}"
export OMNIRT_WAV2LIP_FACE_DET_DEVICE="${OMNIRT_WAV2LIP_FACE_DET_DEVICE:-cpu}"

ascend_env="${ASCEND_SET_ENV:-/usr/local/Ascend/ascend-toolkit/set_env.sh}"
omnirt_dir="$DIGITAL_HUMAN_HOME/omnirt"
checkpoint="$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
s3fd="$OMNIRT_MODEL_ROOT/wav2lip/s3fd.pth"

if [[ ! -f "$ascend_env" ]]; then
  echo "Missing Ascend CANN environment file: $ascend_env" >&2
  echo "Set ASCEND_SET_ENV to your real set_env.sh path, then retry." >&2
  exit 1
fi

if [[ ! -d "$omnirt_dir" ]]; then
  echo "Missing OmniRT checkout: $omnirt_dir" >&2
  echo "Expected layout: $DIGITAL_HUMAN_HOME/opentalking and $DIGITAL_HUMAN_HOME/omnirt" >&2
  exit 1
fi

if [[ ! -f "$omnirt_dir/.venv/bin/activate" ]]; then
  echo "Missing OmniRT virtualenv: $omnirt_dir/.venv" >&2
  if uv_bin="$(quickstart_resolve_uv)"; then
    echo "Run this first: cd \"$omnirt_dir\" && \"$uv_bin\" sync --extra server --python 3.11" >&2
  else
    echo "Install uv or add it to PATH, then run: cd \"$omnirt_dir\" && uv sync --extra server --python 3.11" >&2
  fi
  exit 1
fi

if [[ ! -f "$checkpoint" ]]; then
  echo "Missing Wav2Lip checkpoint: $checkpoint" >&2
  exit 1
fi

if [[ ! -f "$s3fd" ]]; then
  echo "Missing S3FD checkpoint: $s3fd" >&2
  exit 1
fi

if ! quickstart_resolve_uv >/dev/null 2>&1; then
  echo "Unable to find uv in PATH or common install locations." >&2
  echo "The OmniRT helper can reuse an existing virtualenv, but install or expose uv before running dependency setup on this host." >&2
fi

echo "Preparing Ascend 910B deployment"
echo "  repo:    $repo_root"
echo "  home:    $DIGITAL_HUMAN_HOME"
echo "  omnirt:  $omnirt_dir"
echo "  models:  $OMNIRT_MODEL_ROOT"
echo "  cann:    $ascend_env"
echo "  device:  $OMNIRT_WAV2LIP_DEVICE"
echo "  face det: $OMNIRT_WAV2LIP_FACE_DET_DEVICE"

quickstart_source_ascend_env "$ascend_env"

bash "$quickstart_dir/start_omnirt_wav2lip.sh" --device npu "${forward_args[@]}"
