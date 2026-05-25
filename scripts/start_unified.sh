#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
quickstart_dir="$script_dir/quickstart"
# shellcheck disable=SC1091
source "$quickstart_dir/_helpers.sh"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/start_unified.sh [--mock]
  bash scripts/start_unified.sh --backend local --model MODEL [--api-port PORT] [--web-port PORT]
  bash scripts/start_unified.sh --backend omnirt --model MODEL --omnirt URL [--api-port PORT] [--web-port PORT]

Options:
  --mock             Use the built-in Mock backend. No model weights or OmniRT required.
  --backend BACKEND  One of: mock, local, omnirt, direct_ws.
  --model MODEL      Model name whose backend should be overridden, for example quicktalk.
  --omnirt URL       OmniRT base URL, for example http://127.0.0.1:9000.
  --api-port PORT    OpenTalking API / unified backend port.
  --web-port PORT    WebUI dev server port.
  --host HOST        WebUI bind host. API host can still be set with OPENTALKING_API_HOST.
  --env FILE         Source a quickstart env file before starting services.
  --help             Show this help.

Examples:
  bash scripts/start_unified.sh --mock
  bash scripts/start_unified.sh --backend local --model quicktalk
  bash scripts/start_unified.sh --backend omnirt --model flashtalk --omnirt http://127.0.0.1:9000
USAGE
}

backend=""
model=""
omnirt_url=""
api_port=""
web_port=""
web_host=""
env_file=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mock)
      backend="mock"
      shift
      ;;
    --backend)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --backend" >&2
        exit 2
      fi
      backend="$2"
      shift 2
      ;;
    --model)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --model" >&2
        exit 2
      fi
      model="$2"
      shift 2
      ;;
    --omnirt)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --omnirt" >&2
        exit 2
      fi
      omnirt_url="$2"
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
    --host)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --host" >&2
        exit 2
      fi
      web_host="$2"
      shift 2
      ;;
    --env)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --env" >&2
        exit 2
      fi
      env_file="$2"
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

backend="${backend:-mock}"
backend="$(printf '%s' "$backend" | tr '[:upper:]' '[:lower:]')"
case "$backend" in
  mock|local|omnirt|direct_ws) ;;
  *)
    echo "Invalid --backend: $backend" >&2
    echo "Expected one of: mock, local, omnirt, direct_ws" >&2
    exit 2
    ;;
esac

if [[ -n "$env_file" ]]; then
  if [[ ! -f "$env_file" ]]; then
    echo "Env file not found: $env_file" >&2
    exit 2
  fi
  export OPENTALKING_QUICKSTART_ENV="$env_file"
else
  env_file="${OPENTALKING_QUICKSTART_ENV:-$quickstart_dir/env}"
fi
quickstart_source_env "$env_file"

start_args=()
web_args=()
if [[ -n "$api_port" ]]; then
  start_args+=(--api-port "$api_port")
  web_args+=(--api-port "$api_port")
fi
if [[ -n "$web_port" ]]; then
  web_args+=(--web-port "$web_port")
fi
if [[ -n "$web_host" ]]; then
  web_args+=(--host "$web_host")
fi

if [[ "$backend" == "mock" ]]; then
  bash "$quickstart_dir/start_opentalking.sh" --mock "${start_args[@]}"
  bash "$quickstart_dir/start_frontend.sh" "${web_args[@]}"
  echo ""
  echo "Open the app:"
  echo "  http://127.0.0.1:${web_port:-${OPENTALKING_WEB_PORT:-5173}}"
  echo ""
  echo "Select mock / driverless mode to test without a real driver model."
  exit 0
fi

if [[ -z "$model" ]]; then
  echo "--model is required when --backend is $backend." >&2
  exit 2
fi

model_env_name="OPENTALKING_$(printf '%s' "$model" | tr '[:lower:]-' '[:upper:]_')_BACKEND"
export "$model_env_name=$backend"
export OPENTALKING_DEFAULT_MODEL="$model"

if [[ "$backend" == "omnirt" ]]; then
  if [[ -n "$omnirt_url" ]]; then
    start_args+=(--omnirt "$omnirt_url")
  elif [[ -z "${OMNIRT_ENDPOINT:-}" ]]; then
    echo "--omnirt URL is required for --backend omnirt unless OMNIRT_ENDPOINT is set." >&2
    exit 2
  fi
fi

if [[ -n "$omnirt_url" && "$backend" != "omnirt" ]]; then
  export OMNIRT_ENDPOINT="$omnirt_url"
fi

if [[ "$backend" == "local" && "$model" == "musetalk" ]]; then
  export OMNIRT_ENDPOINT=""
  export OPENTALKING_OMNIRT_ENDPOINT=""
  export OPENTALKING_MUSETALK_DEVICE="${OPENTALKING_MUSETALK_DEVICE:-cuda:0}"
  export OPENTALKING_TORCH_DEVICE="${OPENTALKING_TORCH_DEVICE:-$OPENTALKING_MUSETALK_DEVICE}"
  bash "$quickstart_dir/prepare_local_musetalk.sh"
fi

bash "$quickstart_dir/start_opentalking.sh" "${start_args[@]}"
bash "$quickstart_dir/start_frontend.sh" "${web_args[@]}"

echo ""
echo "Open the app:"
echo "  http://127.0.0.1:${web_port:-${OPENTALKING_WEB_PORT:-5173}}"
echo ""
echo "Default model: $model"
echo "Backend override: $model_env_name=$backend"
