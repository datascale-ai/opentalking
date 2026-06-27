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
  bash scripts/quickstart/start_all.sh [--mock] [--omnirt URL] [--api-port PORT] [--web-port PORT]

Examples:
  bash scripts/quickstart/start_all.sh --mock
  bash scripts/quickstart/start_all.sh --mock --api-port 8010 --web-port 5180
  bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000 --api-port 8010 --web-port 5180

This starts OpenTalking API and frontend. It does not start OmniRT itself.
--api_port and --web_port are accepted as aliases for the dashed options.
The API port is mapped to OPENTALKING_UNIFIED_PORT and VITE_BACKEND_PORT.
Start OmniRT Wav2Lip or FlashTalk first when using a real driver model.
USAGE
}

mode_args=()
api_port=""
web_port=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mock)
      mode_args+=(--mock)
      shift
      ;;
    --omnirt)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --omnirt" >&2
        exit 2
      fi
      mode_args+=(--omnirt "$2")
      shift 2
      ;;
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

if [[ -n "$api_port" ]]; then
  mode_args+=(--api-port "$api_port")
fi
web_args=()
if [[ -n "$web_port" ]]; then
  web_args+=(--web-port "$web_port")
fi
if [[ -n "$api_port" ]]; then
  web_args+=(--api-port "$api_port")
fi

bash "$script_dir/start_opentalking.sh" "${mode_args[@]}"
bash "$script_dir/start_frontend.sh" "${web_args[@]}"

echo ""
echo "Open the app:"
echo "  http://127.0.0.1:${web_port:-${OPENTALKING_WEB_PORT:-5173}}"
