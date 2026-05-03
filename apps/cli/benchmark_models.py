from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np

from opentalking.core.interfaces.model_adapter import ModelAdapter
from opentalking.core.types.frames import AudioChunk
from opentalking.models import get_adapter
from opentalking.worker.pipeline.render_pipeline import (
    render_audio_chunk_sync,
    reset_avatar_speech_state,
)


_DEFAULT_AVATARS = {
    "wav2lip": "demo-avatar",
    "musetalk": "demo-musetalk",
}


def _speechlike_pcm(samples: int, sample_rate: int) -> np.ndarray:
    t = np.arange(samples, dtype=np.float32) / max(1, sample_rate)
    envelope = 0.55 + 0.45 * np.sin(2.0 * np.pi * 3.0 * t)
    signal = (
        0.55 * np.sin(2.0 * np.pi * 180.0 * t)
        + 0.30 * np.sin(2.0 * np.pi * 320.0 * t)
        + 0.15 * np.sin(2.0 * np.pi * 620.0 * t)
    )
    return np.clip(signal * envelope * 1800.0, -32768.0, 32767.0).astype(np.int16)


def _gpu_name() -> str | None:
    try:
        import torch
    except Exception:
        return None
    if not torch.cuda.is_available():
        return None
    return torch.cuda.get_device_name(0)


def _sync_device(device: str) -> None:
    if not device.startswith("cuda"):
        return
    try:
        import torch
    except Exception:
        return
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _set_stream_context(
    *,
    model_type: str,
    avatar_state: object,
    chunk: AudioChunk,
    next_chunk: AudioChunk | None,
) -> None:
    extra = getattr(avatar_state, "extra", None)
    if model_type != "wav2lip" or not isinstance(extra, dict):
        return
    extra["wav2lip_stream_is_final"] = next_chunk is None
    extra["wav2lip_stream_lookahead_pcm"] = (
        np.zeros(0, dtype=np.int16)
        if next_chunk is None
        else np.asarray(next_chunk.data, dtype=np.int16).reshape(-1).copy()
    )


def _render_chunks(
    *,
    model_type: str,
    adapter: ModelAdapter,
    avatar_state: object,
    chunks: list[AudioChunk],
    device: str,
) -> tuple[int, list[float]]:
    frame_idx = 0
    rendered_frames = 0
    wall_chunks: list[float] = []
    for i, chunk in enumerate(chunks):
        next_chunk = chunks[i + 1] if i + 1 < len(chunks) else None
        _set_stream_context(
            model_type=model_type,
            avatar_state=avatar_state,
            chunk=chunk,
            next_chunk=next_chunk,
        )
        chunk_started = time.perf_counter()
        next_frame_idx, frames = render_audio_chunk_sync(
            adapter,
            avatar_state,
            chunk,
            frame_index_start=frame_idx,
            speech_frame_index_start=frame_idx,
        )
        _sync_device(device)
        wall_chunks.append(time.perf_counter() - chunk_started)
        rendered_frames += len(frames)
        frame_idx = int(next_frame_idx)
    return rendered_frames, wall_chunks


def benchmark_model(
    *,
    model_type: str,
    avatar_path: Path,
    device: str,
    duration_s: float,
    chunk_ms: float,
    warmup_chunks: int,
) -> dict[str, object]:
    adapter = get_adapter(model_type)
    adapter.load_model(device)
    avatar_state = adapter.load_avatar(str(avatar_path))
    adapter.warmup()

    sample_rate = int(avatar_state.manifest.sample_rate)
    samples_per_chunk = max(1, int(sample_rate * chunk_ms / 1000.0))
    chunks = max(1, int(round(duration_s * 1000.0 / chunk_ms)))
    total_chunks = max(0, warmup_chunks) + chunks
    audio_chunks = [
        AudioChunk(
            data=_speechlike_pcm(samples_per_chunk, sample_rate),
            sample_rate=sample_rate,
            duration_ms=1000.0 * samples_per_chunk / sample_rate,
        )
        for _ in range(total_chunks)
    ]

    warmup_audio = audio_chunks[: max(0, warmup_chunks)]
    if warmup_audio:
        _render_chunks(
            model_type=model_type,
            adapter=adapter,
            avatar_state=avatar_state,
            chunks=warmup_audio,
            device=device,
        )
        reset_avatar_speech_state(avatar_state)

    measure_audio = audio_chunks[max(0, warmup_chunks) :]
    _sync_device(device)
    started = time.perf_counter()
    rendered_frames, wall_chunks = _render_chunks(
        model_type=model_type,
        adapter=adapter,
        avatar_state=avatar_state,
        chunks=measure_audio,
        device=device,
    )
    wall_s = time.perf_counter() - started

    return {
        "model": model_type,
        "avatar": str(avatar_path),
        "device": device,
        "gpu": _gpu_name(),
        "duration_s": duration_s,
        "chunk_ms": chunk_ms,
        "chunks": chunks,
        "frames": rendered_frames,
        "wall_s": round(wall_s, 4),
        "fps": round(rendered_frames / max(wall_s, 1e-9), 2),
        "avg_chunk_ms": round((sum(wall_chunks) / max(1, len(wall_chunks))) * 1000.0, 2),
        "p95_chunk_ms": round(float(np.percentile(np.asarray(wall_chunks), 95)) * 1000.0, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark built-in OpenTalking model adapters.")
    parser.add_argument("--model", choices=["wav2lip", "musetalk", "all"], default="all")
    parser.add_argument("--avatars-root", type=Path, default=Path("examples/avatars"))
    parser.add_argument("--device", default=os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda:0"))
    parser.add_argument("--duration-s", type=float, default=3.0)
    parser.add_argument("--chunk-ms", type=float, default=200.0)
    parser.add_argument("--warmup-chunks", type=int, default=3)
    args = parser.parse_args()

    models = ["wav2lip", "musetalk"] if args.model == "all" else [args.model]
    results = []
    for model_type in models:
        avatar_path = args.avatars_root / _DEFAULT_AVATARS[model_type]
        results.append(
            benchmark_model(
                model_type=model_type,
                avatar_path=avatar_path,
                device=args.device,
                duration_s=args.duration_s,
                chunk_ms=args.chunk_ms,
                warmup_chunks=args.warmup_chunks,
            )
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
