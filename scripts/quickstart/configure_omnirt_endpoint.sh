#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../.." && pwd)"
default_home="$(cd -- "$repo_root/.." && pwd)"

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
if [[ -f "$env_file" ]]; then
  # shellcheck disable=SC1090
  source "$env_file"
fi

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/quickstart/configure_omnirt_endpoint.sh [URL]

Example:
  bash scripts/quickstart/configure_omnirt_endpoint.sh http://127.0.0.1:9000
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$default_home}"
endpoint="${1:-${OMNIRT_ENDPOINT:-http://127.0.0.1:${OMNIRT_PORT:-9000}}}"
path_template="${OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE:-/v1/audio2video/{model}}"
opentalking_env="$repo_root/.env"

if [[ ! -f "$opentalking_env" && -f "$repo_root/.env.example" ]]; then
  cp "$repo_root/.env.example" "$opentalking_env"
fi

set_env_key() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if [[ -f "$opentalking_env" ]]; then
    awk -v key="$key" -v line="$key=$value" '
      BEGIN { done = 0 }
      $0 ~ "^" key "=" { print line; done = 1; next }
      { print }
      END { if (!done) print line }
    ' "$opentalking_env" > "$tmp"
  else
    printf '%s=%s\n' "$key" "$value" > "$tmp"
  fi
  mv "$tmp" "$opentalking_env"
}

set_env_key "OMNIRT_ENDPOINT" "$endpoint"
set_env_key "OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE" "$path_template"

echo "Configured OpenTalking OmniRT endpoint:"
echo "  $opentalking_env"
echo "  OMNIRT_ENDPOINT=$endpoint"
echo "  OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE=$path_template"
