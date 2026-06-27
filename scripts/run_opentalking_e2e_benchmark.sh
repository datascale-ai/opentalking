#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
python_bin="${OPENTALKING_BENCHMARK_PYTHON:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  else
    python_bin="${PYTHON:-python3}"
  fi
fi

config="$repo_root/configs/benchmark/opentalking-e2e.yaml"
backend="omnirt"
model="all"
api_base_url=""
api_port=""
web_port=""
host=""
avatar_id=""
tester=""
gpu_index=""
timeout="240"
out_dir=""
reuse_omnirt=0
keep_omnirt=0

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/run_opentalking_e2e_benchmark.sh --tester zcm [options]

Options:
  --model MODEL         wav2lip, musetalk, quicktalk, or all. Default: all.
  --backend BACKEND     Backend type. Default: omnirt.
  --tester NAME         Tester name. Required.
  --api-base-url URL    OpenTalking API base URL. Default: from config.
  --api-port PORT       API port override. Default: from config.
  --web-port PORT       Web port override. Default: from config.
  --host HOST           Web bind host override. Default: from config.
  --avatar-id ID        Avatar id. Default: config value.
  --gpu-index INDEX     GPU index override.
  --timeout SECONDS     Benchmark timeout. Default: 240.
  --out-dir DIR         Output directory override for a single run.
  --reuse-omnirt        Reuse an already-running OmniRT service; cold start excludes OmniRT.
  --keep-omnirt         Keep benchmark-started OmniRT running after the test.
  --help                Show this help.

Examples:
  bash scripts/run_opentalking_e2e_benchmark.sh --tester zcm --model wav2lip
  bash scripts/run_opentalking_e2e_benchmark.sh --tester zcm --model all
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      [[ $# -ge 2 ]] || { echo "Missing value for --model" >&2; exit 2; }
      model="$2"
      shift 2
      ;;
    --backend)
      [[ $# -ge 2 ]] || { echo "Missing value for --backend" >&2; exit 2; }
      backend="$2"
      shift 2
      ;;
    --tester)
      [[ $# -ge 2 ]] || { echo "Missing value for --tester" >&2; exit 2; }
      tester="$2"
      shift 2
      ;;
    --api-base-url)
      [[ $# -ge 2 ]] || { echo "Missing value for --api-base-url" >&2; exit 2; }
      api_base_url="$2"
      shift 2
      ;;
    --api-port)
      [[ $# -ge 2 ]] || { echo "Missing value for --api-port" >&2; exit 2; }
      api_port="$2"
      shift 2
      ;;
    --web-port)
      [[ $# -ge 2 ]] || { echo "Missing value for --web-port" >&2; exit 2; }
      web_port="$2"
      shift 2
      ;;
    --host)
      [[ $# -ge 2 ]] || { echo "Missing value for --host" >&2; exit 2; }
      host="$2"
      shift 2
      ;;
    --avatar-id)
      [[ $# -ge 2 ]] || { echo "Missing value for --avatar-id" >&2; exit 2; }
      avatar_id="$2"
      shift 2
      ;;
    --gpu-index)
      [[ $# -ge 2 ]] || { echo "Missing value for --gpu-index" >&2; exit 2; }
      gpu_index="$2"
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || { echo "Missing value for --timeout" >&2; exit 2; }
      timeout="$2"
      shift 2
      ;;
    --out-dir)
      [[ $# -ge 2 ]] || { echo "Missing value for --out-dir" >&2; exit 2; }
      out_dir="$2"
      shift 2
      ;;
    --reuse-omnirt)
      reuse_omnirt=1
      shift
      ;;
    --keep-omnirt)
      keep_omnirt=1
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

if [[ -z "$tester" ]]; then
  echo "--tester is required" >&2
  exit 2
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Python not found: $python_bin" >&2
  exit 1
fi

if [[ ! -f "$config" ]]; then
  echo "Config not found: $config" >&2
  exit 1
fi

run_one() {
  local one_model="$1"
  local one_out_dir="$2"
  local args=("$repo_root/scripts/benchmark_opentalking_e2e.py" --config "$config" --repo-root "$repo_root" --backend "$backend" --model "$one_model" --tester "$tester" --timeout "$timeout")
  [[ -n "$api_base_url" ]] && args+=(--api-base-url "$api_base_url")
  [[ -n "$api_port" ]] && args+=(--api-port "$api_port")
  [[ -n "$web_port" ]] && args+=(--web-port "$web_port")
  [[ -n "$host" ]] && args+=(--host "$host")
  [[ -n "$avatar_id" ]] && args+=(--avatar-id "$avatar_id")
  [[ -n "$gpu_index" ]] && args+=(--gpu-index "$gpu_index")
  [[ -n "$one_out_dir" ]] && args+=(--out-dir "$one_out_dir")
  [[ "$reuse_omnirt" == "1" ]] && args+=(--reuse-omnirt)
  [[ "$keep_omnirt" == "1" ]] && args+=(--keep-omnirt)
  "$python_bin" "${args[@]}"
}

case "$model" in
  all)
    for one_model in wav2lip musetalk quicktalk; do
      run_one "$one_model" ""
    done
    ;;
  wav2lip|musetalk|quicktalk)
    run_one "$model" "$out_dir"
    ;;
  *)
    echo "Invalid --model: $model" >&2
    echo "Expected one of: wav2lip, musetalk, quicktalk, all" >&2
    exit 2
    ;;
esac
