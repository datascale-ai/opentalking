from __future__ import annotations

import concurrent.futures
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

from opentalking.engine.inference import infer_params

RANK = int(os.environ.get("RANK", 0))
WORLD_SIZE = int(os.environ.get("WORLD_SIZE", 1))

CMD_INIT = 0
CMD_GENERATE = 1
CMD_SHUTDOWN = 2
CMD_NONE = -1

MAGIC_AUDIO = b"AUDI"
MAGIC_VIDEO = b"VIDX"

FRAME_NUM = infer_params["frame_num"]
MOTION_FRAMES_NUM = infer_params["motion_frames_num"]
SLICE_LEN = FRAME_NUM - MOTION_FRAMES_NUM
SAMPLE_RATE = infer_params["sample_rate"]
TGT_FPS = infer_params["tgt_fps"]
CACHED_AUDIO_DURATION = infer_params["cached_audio_duration"]
HEIGHT = infer_params["height"]
WIDTH = infer_params["width"]

JPEG_QUALITY = min(100, max(1, int(os.environ.get("FLASHTALK_JPEG_QUALITY", "40"))))
JPEG_WORKERS = max(1, int(os.environ.get("FLASHTALK_JPEG_WORKERS", "1")))
PROGRESSIVE_SEND = os.environ.get("FLASHTALK_PROGRESSIVE_SEND", "0") == "1"
WARMUP_ON_STARTUP = os.environ.get("FLASHTALK_WARMUP", "0") == "1"
WARMUP_ON_INIT = os.environ.get("FLASHTALK_WARMUP_ON_INIT", "0") == "1"
WARMUP_REF_IMAGE = os.environ.get("FLASHTALK_WARMUP_REF_IMAGE", "").strip()
WARMUP_PROMPT = os.environ.get(
    "FLASHTALK_WARMUP_PROMPT",
    "A person is talking. Only the foreground characters are moving, the background remains static.",
)
WARMUP_SEED = int(os.environ.get("FLASHTALK_WARMUP_SEED", "9999"))
IDLE_PRELOAD_REFS = [
    item.strip()
    for item in os.environ.get("FLASHTALK_IDLE_PRELOAD_REFS", "").split(",")
    if item.strip()
]
IDLE_CACHE_CHUNKS = max(0, int(os.environ.get("FLASHTALK_IDLE_CACHE_CHUNKS", "4")))
IDLE_CACHE_LEVEL = max(
    0.0,
    float(os.environ.get("FLASHTALK_IDLE_CACHE_LEVEL", "480")) / 32768.0,
)
IDLE_CACHE_CROSSFADE_FRAMES = max(
    0, int(os.environ.get("FLASHTALK_IDLE_CACHE_CROSSFADE_FRAMES", "6"))
)
IDLE_CACHE_PLAYBACK = os.environ.get("FLASHTALK_IDLE_CACHE_PLAYBACK", "pingpong").lower()
IDLE_ENTER_CHUNKS = max(1, int(os.environ.get("FLASHTALK_IDLE_ENTER_CHUNKS", "2")))
IDLE_SILENCE_RMS = max(
    0.0, float(os.environ.get("FLASHTALK_IDLE_SILENCE_RMS", "0.004"))
)
IDLE_REFRESH_INTERVAL = max(
    1, int(os.environ.get("FLASHTALK_IDLE_REFRESH_INTERVAL", "3"))
)
IDLE_HOLD_MIN_CHUNKS = max(
    1, int(os.environ.get("FLASHTALK_IDLE_HOLD_MIN_CHUNKS", "1"))
)
IDLE_HOLD_MAX_CHUNKS = max(
    IDLE_HOLD_MIN_CHUNKS,
    int(os.environ.get("FLASHTALK_IDLE_HOLD_MAX_CHUNKS", "3")),
)
IDLE_MOUTH_LOCK = min(
    1.0, max(0.0, float(os.environ.get("FLASHTALK_IDLE_MOUTH_LOCK", "0.97")))
)
IDLE_MOUTH_TEMPORAL = min(
    1.0, max(0.0, float(os.environ.get("FLASHTALK_IDLE_MOUTH_TEMPORAL", "0.85")))
)
IDLE_EYE_LOCK = min(
    1.0, max(0.0, float(os.environ.get("FLASHTALK_IDLE_EYE_LOCK", "0.65")))
)
IDLE_EYE_TEMPORAL = min(
    1.0, max(0.0, float(os.environ.get("FLASHTALK_IDLE_EYE_TEMPORAL", "0.75")))
)
IDLE_RANDOM_SEED = int(os.environ.get("FLASHTALK_IDLE_RANDOM_SEED", "20260415"))
IDLE_CACHE_VERSION = int(os.environ.get("FLASHTALK_IDLE_CACHE_VERSION", "2"))
IDLE_CACHE_DIR = Path(
    os.environ.get(
        "FLASHTALK_IDLE_CACHE_DIR",
        os.path.join(tempfile.gettempdir(), "flashtalk_idle_cache"),
    )
).expanduser()

AUDIO_CHUNK_SAMPLES = SLICE_LEN * SAMPLE_RATE // TGT_FPS
AUDIO_CHUNK_BYTES = AUDIO_CHUNK_SAMPLES * 2
CACHED_AUDIO_SAMPLES = SAMPLE_RATE * CACHED_AUDIO_DURATION
AUDIO_END_IDX = CACHED_AUDIO_DURATION * TGT_FPS
AUDIO_START_IDX = AUDIO_END_IDX - FRAME_NUM

STREAM_DECODE = os.environ.get("FLASHTALK_STREAM_DECODE", "0") == "1"
DEFERRED_MOTION = os.environ.get("FLASHTALK_DEFERRED_MOTION", "1") == "1"

_BCAST_DEVICE: torch.device = torch.device("cpu")
_PROCESS_START_TIME = time.time()
_CMD_SEQ = 0
_CMD_LAST_SEQ = 0
_AUDIO_EMBEDDING_SHAPE_CACHED: tuple[int, ...] | None = None
_IDLE_CACHE_MEMORY: dict[str, list[np.ndarray]] = {}
_JPEG_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None


def _command_file_path() -> str:
    cmd_dir = os.environ.get("FLASHTALK_CMD_DIR", tempfile.gettempdir())
    port = os.environ.get("MASTER_PORT", "29500")
    return os.path.join(cmd_dir, f"flashtalk_cmd_{port}.json")


def _write_command(cmd: int) -> int:
    global _CMD_SEQ
    _CMD_SEQ += 1
    path = _command_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    payload = {"seq": _CMD_SEQ, "cmd": cmd}
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp_path, path)
    return cmd


def _wait_for_command() -> int:
    global _CMD_LAST_SEQ
    path = _command_file_path()
    while True:
        try:
            if os.path.getmtime(path) < _PROCESS_START_TIME - 1.0:
                time.sleep(0.05)
                continue
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            seq = int(payload.get("seq", 0))
            cmd = int(payload.get("cmd", CMD_NONE))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            time.sleep(0.05)
            continue

        if seq > _CMD_LAST_SEQ and cmd != CMD_NONE:
            _CMD_LAST_SEQ = seq
            return cmd
        time.sleep(0.05)


def _append_audio_chunk(audio_buffer: np.ndarray, write_pos: int, chunk_audio: np.ndarray) -> int:
    buf_len = audio_buffer.shape[0]
    chunk_len = int(chunk_audio.shape[0])
    if chunk_len >= buf_len:
        audio_buffer[:] = chunk_audio[-buf_len:]
        return 0

    end = write_pos + chunk_len
    if end <= buf_len:
        audio_buffer[write_pos:end] = chunk_audio
    else:
        first = buf_len - write_pos
        audio_buffer[write_pos:] = chunk_audio[:first]
        audio_buffer[: end - buf_len] = chunk_audio[first:]
    return end % buf_len


def _linearize_audio_buffer(audio_buffer: np.ndarray, write_pos: int) -> np.ndarray:
    if write_pos == 0:
        return audio_buffer.copy()
    return np.concatenate([audio_buffer[write_pos:], audio_buffer[:write_pos]])


def _chunk_rms(chunk_audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(chunk_audio, dtype=np.float32), dtype=np.float32)))


def _reset_audio_embedding_shape_cache() -> None:
    global _AUDIO_EMBEDDING_SHAPE_CACHED
    _AUDIO_EMBEDDING_SHAPE_CACHED = None
