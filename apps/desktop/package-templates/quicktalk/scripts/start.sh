#!/usr/bin/env bash
set -euo pipefail

package_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
api_port="${OPENTALKING_API_PORT:-8010}"
repo_root="${OPENTALKING_REPO_ROOT:-$package_root/opentalking}"
log_dir="$package_root/logs"

mkdir -p "$log_dir"

export OPENTALKING_DEFAULT_MODEL="${OPENTALKING_DEFAULT_MODEL:-quicktalk}"
export OPENTALKING_QUICKTALK_BACKEND="${OPENTALKING_QUICKTALK_BACKEND:-local}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$package_root/models/quicktalk}"

if [[ -z "${OPENTALKING_FFMPEG_BIN:-}" ]]; then
  if [[ -x "$package_root/binary/ffmpeg" ]]; then
    export OPENTALKING_FFMPEG_BIN="$package_root/binary/ffmpeg"
    export PATH="$package_root/binary:$PATH"
  else
    export OPENTALKING_FFMPEG_BIN="ffmpeg"
  fi
fi

{
  echo "Starting OpenTalking QuickTalk package"
  echo "  package: $package_root"
  echo "  repo:    $repo_root"
  echo "  model:   $OPENTALKING_QUICKTALK_ASSET_ROOT"
  echo "  api:     $api_port"
  echo "  ffmpeg:  $OPENTALKING_FFMPEG_BIN"
} >"$log_dir/start.log"

if [[ -x "$repo_root/scripts/start_unified.sh" || -f "$repo_root/scripts/start_unified.sh" ]]; then
  cd "$repo_root"
  bash scripts/start_unified.sh --backend local --model quicktalk --api-port "$api_port" >>"$log_dir/start.log" 2>&1
  exit $?
fi

if [[ -x "$package_root/bin/opentalking-unified" ]]; then
  "$package_root/bin/opentalking-unified" >>"$log_dir/start.log" 2>&1 &
  echo "$!" >"$log_dir/opentalking-package.pid"
  exit 0
fi

echo "No OpenTalking backend entry found. Expected $repo_root/scripts/start_unified.sh or $package_root/bin/opentalking-unified." >>"$log_dir/start.log"
exit 1
