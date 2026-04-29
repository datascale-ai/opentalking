#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${OPENTALKING_FLASHTALK_HOST:-0.0.0.0}"
PORT="${OPENTALKING_FLASHTALK_PORT:-8765}"
NPROC="${OPENTALKING_FLASHTALK_GPU_COUNT:-8}"
CKPT_DIR="${OPENTALKING_FLASHTALK_CKPT_DIR:-./models/SoulX-FlashTalk-14B}"
WAV2VEC_DIR="${OPENTALKING_FLASHTALK_WAV2VEC_DIR:-./models/chinese-wav2vec2-base}"

PYTHON_BIN="${PYTHON:-python}"

exec "${PYTHON_BIN}" -m torch.distributed.run --nproc_per_node="${NPROC}" -m opentalking.server \
  --host "${HOST}" \
  --port "${PORT}" \
  --ckpt_dir "${CKPT_DIR}" \
  --wav2vec_dir "${WAV2VEC_DIR}" \
  "$@"
