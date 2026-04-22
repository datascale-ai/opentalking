from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time
from typing import Any, Protocol

import numpy as np

from opentalking.core.interfaces.model_adapter import ModelAdapter
from opentalking.core.types.frames import AudioChunk, VideoFrameData

log = logging.getLogger(__name__)
_OVERLAP_FRAMES = int(os.environ.get("OPENTALKING_MUSETALK_OVERLAP_FRAMES", "0"))


class VideoSink(Protocol):
    async def __call__(self, frame: VideoFrameData) -> None: ...


@dataclass
class RenderedChunkData:
    next_frame_idx: int
    features: Any
    predictions: list[Any]
    frames: list[VideoFrameData]


def reset_avatar_speech_state(avatar_state: Any) -> None:
    """Reset per-utterance streaming state so live and offline renders stay reproducible."""
    extra = getattr(avatar_state, "extra", None)
    if not isinstance(extra, dict):
        return
    extra["audio_context_pcm"] = np.zeros(0, dtype=np.int16)
    extra["feature_overlap_tail"] = None
    extra["prediction_overlap_tail"] = []
    extra["audio_total_samples"] = 0
    extra["speech_frame_index_start"] = 0
    if "musetalk_prev_energy" in extra:
        extra["musetalk_prev_energy"] = 0.0
    if "wav2lip_prev_open" in extra:
        extra["wav2lip_prev_open"] = 0.0
    if "wav2lip_prev_frame_pos" in extra:
        extra["wav2lip_prev_frame_pos"] = 0.0
    if "wav2lip_stream_pcm" in extra:
        extra["wav2lip_stream_pcm"] = np.zeros(0, dtype=np.int16)
    if "wav2lip_stream_lookahead_pcm" in extra:
        extra["wav2lip_stream_lookahead_pcm"] = np.zeros(0, dtype=np.int16)
    if "wav2lip_stream_emitted_frames" in extra:
        extra["wav2lip_stream_emitted_frames"] = 0
    if "wav2lip_stream_is_final" in extra:
        extra["wav2lip_stream_is_final"] = False
    if "rendering_speech" in extra:
        extra["rendering_speech"] = False


def _extract_chunk_features(
    adapter: ModelAdapter,
    avatar_state: Any,
    chunk: AudioChunk,
    *,
    streaming: bool,
) -> Any:
    if streaming:
        extract_for_stream = getattr(adapter, "extract_features_for_stream", None)
        if callable(extract_for_stream):
            return extract_for_stream(chunk, avatar_state)
    return adapter.extract_features(chunk)


def _infer_predictions(
    adapter: ModelAdapter,
    avatar_state: Any,
    features: Any,
    *,
    frame_index_start: int,
    infer_batch_frames: int | None,
) -> list[Any]:
    if not infer_batch_frames or infer_batch_frames <= 0:
        return adapter.infer(features, avatar_state)

    vector = getattr(features, "vector", None)
    frame_count = int(getattr(features, "frame_count", 0) or 0)
    if not isinstance(vector, np.ndarray) or vector.ndim < 1 or frame_count <= infer_batch_frames:
        return adapter.infer(features, avatar_state)

    feature_type = type(features)
    frame_energy = getattr(features, "frame_energy", None)
    batched_predictions: list[Any] = []
    for batch_start in range(0, frame_count, infer_batch_frames):
        batch_end = min(frame_count, batch_start + infer_batch_frames)
        batch_kwargs: dict[str, Any] = {
            "vector": vector[batch_start:batch_end],
            "frame_count": batch_end - batch_start,
        }
        if isinstance(frame_energy, np.ndarray):
            batch_kwargs["frame_energy"] = np.asarray(
                frame_energy[batch_start:batch_end],
                dtype=np.float32,
            )
        batch_features = feature_type(**batch_kwargs)
        if hasattr(avatar_state, "extra") and isinstance(getattr(avatar_state, "extra", None), dict):
            avatar_state.extra["frame_index_start"] = frame_index_start + batch_start
        batched_predictions.extend(adapter.infer(batch_features, avatar_state))
    if hasattr(avatar_state, "extra") and isinstance(getattr(avatar_state, "extra", None), dict):
        avatar_state.extra["frame_index_start"] = frame_index_start
    return batched_predictions


def _apply_prediction_overlap(
    avatar_state: Any,
    predictions: list[Any],
) -> list[Any]:
    prev_pred_tail = None
    if hasattr(avatar_state, "extra") and isinstance(getattr(avatar_state, "extra", None), dict):
        prev_pred_tail = avatar_state.extra.get("prediction_overlap_tail")
    if isinstance(prev_pred_tail, list) and predictions:
        overlap = min(_OVERLAP_FRAMES, len(prev_pred_tail), len(predictions))
        for i in range(overlap):
            prev = prev_pred_tail[len(prev_pred_tail) - overlap + i]
            cur = predictions[i]
            if isinstance(prev, np.ndarray) and isinstance(cur, np.ndarray):
                alpha = float(i + 1) / float(overlap + 1)
                predictions[i] = (
                    prev.astype(np.float32) * (1.0 - alpha)
                    + cur.astype(np.float32) * alpha
                ).clip(0.0, 255.0).astype(np.uint8)
    if hasattr(avatar_state, "extra") and isinstance(getattr(avatar_state, "extra", None), dict):
        if predictions and _OVERLAP_FRAMES > 0:
            avatar_state.extra["prediction_overlap_tail"] = [
                p.copy() if isinstance(p, np.ndarray) else p
                for p in predictions[-_OVERLAP_FRAMES:]
            ]
        else:
            avatar_state.extra["prediction_overlap_tail"] = []
    return predictions


def prepare_rendered_chunk_sync(
    adapter: ModelAdapter,
    avatar_state: Any,
    chunk: AudioChunk,
    *,
    frame_index_start: int,
    speech_frame_index_start: int,
    streaming: bool = True,
    infer_batch_frames: int | None = None,
) -> RenderedChunkData:
    """Run one audio chunk through the shared live/offline render pipeline."""
    extra = getattr(avatar_state, "extra", None)
    if isinstance(extra, dict):
        extra["frame_index_start"] = frame_index_start
        extra["speech_frame_index_start"] = speech_frame_index_start
        extra["rendering_speech"] = True

    try:
        features = _extract_chunk_features(
            adapter,
            avatar_state,
            chunk,
            streaming=streaming,
        )
        predictions = _infer_predictions(
            adapter,
            avatar_state,
            features,
            frame_index_start=frame_index_start,
            infer_batch_frames=infer_batch_frames,
        )
        predictions = _apply_prediction_overlap(avatar_state, predictions)

        idx = frame_index_start
        frames: list[VideoFrameData] = []
        for pred in predictions:
            frames.append(adapter.compose_frame(avatar_state, idx, pred))
            idx += 1
        return RenderedChunkData(
            next_frame_idx=idx,
            features=features,
            predictions=predictions,
            frames=frames,
        )
    finally:
        if isinstance(extra, dict):
            extra["rendering_speech"] = False


def render_audio_chunk_sync(
    adapter: ModelAdapter,
    avatar_state: Any,
    chunk: AudioChunk,
    *,
    frame_index_start: int,
    speech_frame_index_start: int,
) -> tuple[int, list[VideoFrameData]]:
    """Process one audio chunk through model; returns next frame index and frames."""
    log.info(
        "render_audio_chunk: start (chunk_dur=%.0fms, idx=%d, speech_idx=%d)",
        chunk.duration_ms,
        frame_index_start,
        speech_frame_index_start,
    )
    t0 = time.perf_counter()
    if hasattr(avatar_state, "extra") and isinstance(getattr(avatar_state, "extra", None), dict):
        avatar_state.extra["frame_index_start"] = frame_index_start
        avatar_state.extra["speech_frame_index_start"] = speech_frame_index_start
    rendered = prepare_rendered_chunk_sync(
        adapter,
        avatar_state,
        chunk,
        frame_index_start=frame_index_start,
        speech_frame_index_start=speech_frame_index_start,
        streaming=True,
    )
    t1 = time.perf_counter()
    n = rendered.next_frame_idx - frame_index_start
    log.info(
        "render_chunk: total=%.0fms frames=%d",
        (t1 - t0) * 1000,
        n,
    )
    return rendered.next_frame_idx, rendered.frames


async def render_audio_chunk(
    adapter: ModelAdapter,
    avatar_state: Any,
    chunk: AudioChunk,
    *,
    frame_index_start: int,
    speech_frame_index_start: int,
    video_sink: VideoSink,
) -> int:
    """Backward-compatible async wrapper around synchronous chunk rendering."""
    next_frame_idx, frames = render_audio_chunk_sync(
        adapter,
        avatar_state,
        chunk,
        frame_index_start=frame_index_start,
        speech_frame_index_start=speech_frame_index_start,
    )
    for frame in frames:
        await video_sink(frame)
    return next_frame_idx
