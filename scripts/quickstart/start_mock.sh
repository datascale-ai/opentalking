#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

env_file="${OPENTALKING_QUICKSTART_ENV:-$script_dir/env}"
if [[ -f "$env_file" ]]; then
  # shellcheck disable=SC1090
  source "$env_file"
fi

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/quickstart/start_mock.sh [--api-port PORT] [--web-port PORT]

Examples:
  bash scripts/quickstart/start_mock.sh
  bash scripts/quickstart/start_mock.sh --api-port 8010 --web-port 5180

--api_port and --web_port are accepted as aliases for the dashed options.
USAGE
}

api_port=""
web_port=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-port|--api_port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      api_port="$2"
      shift 2
      ;;
    --web-port|--web_port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      web_port="$2"
      shift 2
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

api_args=(--mock)
web_args=()
if [[ -n "$api_port" ]]; then
  api_args+=(--api-port "$api_port")
  web_args+=(--api-port "$api_port")
fi
if [[ -n "$web_port" ]]; then
  web_args+=(--web-port "$web_port")
fi

echo "Starting OpenTalking mock/self-test mode"
echo "This clears OmniRT endpoint variables for the OpenTalking API process."

bash "$script_dir/start_opentalking.sh" "${api_args[@]}"
bash "$script_dir/start_frontend.sh" "${web_args[@]}"

echo ""
echo "Open the app:"
echo "  http://127.0.0.1:${web_port:-${OPENTALKING_WEB_PORT:-5173}}"
echo ""
echo "Select mock / 无驱动模式 to test without a real driver model."
