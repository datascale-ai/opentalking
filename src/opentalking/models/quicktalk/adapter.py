from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

import numpy as np

from opentalking.avatars.loader import load_avatar_bundle
from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.models.common.frame_avatar import numpy_bgr_to_videoframe
from opentalking.models.registry import register_model

if TYPE_CHECKING:  # pragma: no cover — avoids importing torch/onnx at module load
    from opentalking.models.quicktalk.runtime import RealtimeV3Worker

log = logging.getLogger(__name__)


@dataclass
class QuickTalkFeatures:
    reps: list[np.ndarray]
    audio_feature_seconds: float


@dataclass
class QuickTalkState:
    manifest: AvatarManifest
    worker: RealtimeV3Worker
    fps: float
    frame_index: int = 0
    extra: dict[str, Any] | None = None
    # Per-session LSTM hidden + template cycle position.
    session_state: Any | None = None


# Process-wide cache of ``RealtimeV3Worker`` instances. Building one is
# expensive (~30-120s for the 497-frame restore-context build), but the result
# is purely a function of the avatar bundle + adapter parameters, so the same
# worker can be safely reused across many sessions provided each session keeps
# its own ``RealtimeV3SessionState`` (LSTM hidden + template cycle).
_WORKER_CACHE: dict[tuple[Any, ...], "RealtimeV3Worker"] = {}
_WORKER_CACHE_LOCK = threading.Lock()


def _worker_cache_key(
    *,
    asset_root: Path,
    template_video: Path,
    face_cache_dir: Path,
    device: str,
    output_transform: str,
    scale_h: float,
    scale_w: float,
    resolution: int,
    max_template_seconds: float | None,
    neck_fade_start: float,
    neck_fade_end: float,
    hubert_device: str | None,
) -> tuple[Any, ...]:
    return (
        str(asset_root),
        str(template_video),
        str(face_cache_dir),
        str(device),
        str(output_transform),
        float(scale_h),
        float(scale_w),
        int(resolution),
        float(max_template_seconds) if max_template_seconds is not None else None,
        float(neck_fade_start),
        float(neck_fade_end),
        str(hubert_device) if hubert_device else "",
    )


def _env_value(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _path_from_env_or_metadata(
    name: str,
    metadata: dict[str, Any],
    *keys: str,
) -> Path:
    raw = _env_value(name)
    if not raw:
        for key in keys:
            value = metadata.get(key)
            if value:
                raw = str(value)
                break
    if not raw:
        raise ValueError(f"Missing {name} or avatar metadata key: {', '.join(keys)}")
    return Path(raw).expanduser().resolve()


def _optional_env_path(name: str) -> Path | None:
    raw = _env_value(name)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


@register_model("quicktalk")
class QuickTalkAdapter:
    """QuickTalk realtime worker integrated into OpenTalking's model API."""

    model_type = "quicktalk"

    def __init__(self) -> None:
        self._device = os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda:0")
        # 多卡部署：让 HuBERT 跑在另一张卡，避免与 ONNX 在同一 GPU default
        # stream 上排队。空字符串表示与主 device 同卡（默认行为）。
        self._hubert_device = (
            _env_value("OPENTALKING_QUICKTALK_HUBERT_DEVICE") or None
        )
        self._asset_root = _optional_env_path("OPENTALKING_QUICKTALK_ASSET_ROOT")
        self._output_transform = _env_value(
            "OPENTALKING_QUICKTALK_OUTPUT_TRANSFORM",
            "bgr",
        )
        self._scale_h = float(_env_value("OPENTALKING_QUICKTALK_SCALE_H", "1.6"))
        self._scale_w = float(_env_value("OPENTALKING_QUICKTALK_SCALE_W", "3.6"))
        self._resolution = int(_env_value("OPENTALKING_QUICKTALK_RESOLUTION", "256"))
        self._neck_fade_start = float(_env_value("OPENTALKING_QUICKTALK_NECK_FADE_START", "0.72"))
        self._neck_fade_end = float(_env_value("OPENTALKING_QUICKTALK_NECK_FADE_END", "0.88"))
        self._max_template_seconds_env = _env_value("OPENTALKING_QUICKTALK_MAX_TEMPLATE_SECONDS")
        # Idle frame selection. The template video typically contains the source
        # speaker talking, so cycling all frames during idle makes the avatar
        # appear to keep speaking. We restrict idle to a configurable still
        # frame (default frame 0) or a small loop window where the mouth is
        # closed, so the avatar holds a natural pose between utterances.
        self._idle_frame_index = self._read_int_env(
            "OPENTALKING_QUICKTALK_IDLE_FRAME_INDEX",
            0,
        )
        self._idle_frame_range = self._read_range_env("OPENTALKING_QUICKTALK_IDLE_FRAME_RANGE")

    @staticmethod
    def _read_int_env(name: str, default: int) -> int:
        raw = _env_value(name)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @staticmethod
    def _read_range_env(name: str) -> tuple[int, int] | None:
        raw = _env_value(name)
        if not raw:
            return None
        for sep in (":", "-", ","):
            if sep in raw:
                a, _, b = raw.partition(sep)
                try:
                    lo = int(a.strip())
                    hi = int(b.strip())
                except ValueError:
                    return None
                if hi < lo:
                    lo, hi = hi, lo
                return (lo, hi)
        return None

    def _idle_context_for(self, avatar_state: QuickTalkState, frame_idx: int) -> Any:
        contexts = avatar_state.worker.restore_contexts
        n = len(contexts)
        if n == 0:
            raise RuntimeError("QuickTalk avatar has no restore contexts loaded")
        if self._idle_frame_range is not None:
            lo = max(0, min(self._idle_frame_range[0], n - 1))
            hi = max(lo, min(self._idle_frame_range[1], n - 1))
            span = hi - lo + 1
            return contexts[lo + (frame_idx % span)]
        idx = self._idle_frame_index
        if idx < 0:
            idx = (idx % n + n) % n
        else:
            idx = min(idx, n - 1)
        return contexts[idx]

    def load_model(self, device: str = "cuda") -> None:
        self._device = device

    def load_avatar(self, avatar_path: str) -> QuickTalkState:
        from opentalking.models.quicktalk.runtime import RealtimeV3Worker

        bundle = load_avatar_bundle(Path(avatar_path), strict=False)
        if bundle.manifest.model_type != self.model_type:
            raise ValueError(
                f"Avatar {bundle.manifest.id} model_type={bundle.manifest.model_type}, "
                f"expected {self.model_type}"
            )
        metadata = bundle.manifest.metadata or {}
        asset_root = self._asset_root if self._asset_root is not None else _path_from_env_or_metadata(
            "OPENTALKING_QUICKTALK_ASSET_ROOT",
            metadata,
            "asset_root",
            "quicktalk_asset_root",
        )
        template_video = _path_from_env_or_metadata(
            "OPENTALKING_QUICKTALK_TEMPLATE_VIDEO",
            metadata,
            "template_video",
            "video",
        )
        face_cache_raw = _env_value("OPENTALKING_QUICKTALK_FACE_CACHE_DIR")
        face_cache_dir = Path(face_cache_raw).expanduser().resolve() if face_cache_raw else asset_root / ".face_cache_v3"
        max_template_seconds = (
            float(self._max_template_seconds_env)
            if self._max_template_seconds_env
            else None
        )

        cache_key = _worker_cache_key(
            asset_root=asset_root,
            template_video=template_video,
            face_cache_dir=face_cache_dir,
            device=self._device,
            output_transform=self._output_transform,
            scale_h=self._scale_h,
            scale_w=self._scale_w,
            resolution=self._resolution,
            max_template_seconds=max_template_seconds,
            neck_fade_start=self._neck_fade_start,
            neck_fade_end=self._neck_fade_end,
            hubert_device=self._hubert_device,
        )

        cache_disabled = _env_value("OPENTALKING_QUICKTALK_WORKER_CACHE", "1") == "0"

        worker: RealtimeV3Worker | None = None
        if not cache_disabled:
            worker = _WORKER_CACHE.get(cache_key)
            if worker is not None:
                log.info(
                    "quicktalk worker cache HIT (avatar=%s)", bundle.manifest.id
                )

        if worker is None:
            with _WORKER_CACHE_LOCK:
                if not cache_disabled:
                    worker = _WORKER_CACHE.get(cache_key)
                if worker is None:
                    log.info(
                        "quicktalk worker cache MISS — building (avatar=%s)",
                        bundle.manifest.id,
                    )
                    worker = RealtimeV3Worker(
                        asset_root=asset_root,
                        template_video=template_video,
                        face_cache_dir=face_cache_dir,
                        device=self._device,
                        output_transform=self._output_transform,
                        scale_h=self._scale_h,
                        scale_w=self._scale_w,
                        resolution=self._resolution,
                        max_template_seconds=max_template_seconds,
                        neck_fade_start=self._neck_fade_start,
                        neck_fade_end=self._neck_fade_end,
                        hubert_device=self._hubert_device,
                    )
                    if not cache_disabled:
                        _WORKER_CACHE[cache_key] = worker

        session_state = worker.make_state()
        return QuickTalkState(
            manifest=bundle.manifest,
            worker=worker,
            fps=worker.fps,
            extra={},
            session_state=session_state,
        )

    def warmup(self) -> None:
        return None

    def extract_features(self, audio_chunk: AudioChunk) -> QuickTalkFeatures:
        raise RuntimeError("QuickTalkAdapter.extract_features requires avatar state; use extract_features_for_stream")

    def extract_features_for_stream(
        self,
        audio_chunk: AudioChunk,
        avatar_state: QuickTalkState,
    ) -> QuickTalkFeatures:
        reps, feature_seconds = avatar_state.worker.prepare_pcm_features(
            np.asarray(audio_chunk.data, dtype=np.int16).reshape(-1),
            int(audio_chunk.sample_rate),
        )
        return QuickTalkFeatures(reps=reps, audio_feature_seconds=feature_seconds)

    def infer(self, features: QuickTalkFeatures, avatar_state: QuickTalkState) -> Iterator[np.ndarray]:
        return avatar_state.worker.generate_frames_from_reps(
            features.reps, state=avatar_state.session_state
        )

    def compose_frame(
        self,
        avatar_state: QuickTalkState,
        frame_idx: int,
        prediction: Any,
    ) -> VideoFrameData:
        if not isinstance(prediction, np.ndarray):
            return self.idle_frame(avatar_state, frame_idx)
        return numpy_bgr_to_videoframe(
            prediction,
            frame_idx * (1000.0 / max(1.0, float(avatar_state.fps))),
        )

    def idle_frame(self, avatar_state: QuickTalkState, frame_idx: int) -> VideoFrameData:
        context = self._idle_context_for(avatar_state, frame_idx)
        return numpy_bgr_to_videoframe(
            context.frame.copy(),
            frame_idx * (1000.0 / max(1.0, float(avatar_state.fps))),
        )

    def render_audio_chunk(self, avatar_state: QuickTalkState, audio_chunk: AudioChunk) -> tuple[QuickTalkFeatures, list[VideoFrameData]]:
        reps, feature_seconds = avatar_state.worker.prepare_pcm_features(
            np.asarray(audio_chunk.data, dtype=np.int16).reshape(-1),
            int(audio_chunk.sample_rate),
        )
        features = QuickTalkFeatures(reps=reps, audio_feature_seconds=feature_seconds)
        frames = []
        for prediction in avatar_state.worker.generate_frames_from_reps(
            reps, state=avatar_state.session_state
        ):
            frames.append(self.compose_frame(avatar_state, avatar_state.frame_index, prediction))
            avatar_state.frame_index += 1
        return features, frames
