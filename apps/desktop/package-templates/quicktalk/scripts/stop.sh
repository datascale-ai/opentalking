#!/usr/bin/env bash
set -euo pipefail

package_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
api_port="${OPENTALKING_API_PORT:-8010}"
repo_root="${OPENTALKING_REPO_ROOT:-$package_root/opentalking}"
log_dir="$package_root/logs"

mkdir -p "$log_dir"

if [[ -x "$repo_root/scripts/quickstart/stop_all.sh" || -f "$repo_root/scripts/quickstart/stop_all.sh" ]]; then
  cd "$repo_root"
  bash scripts/quickstart/stop_all.sh --api-port "$api_port" >>"$log_dir/start.log" 2>&1 || true
fi

if [[ -f "$log_dir/opentalking-package.pid" ]]; then
  pid="$(cat "$log_dir/opentalking-package.pid" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$log_dir/opentalking-package.pid"
fi
