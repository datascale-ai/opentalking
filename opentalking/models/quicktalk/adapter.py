from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

import numpy as np

from opentalking.avatar.loader import load_avatar_bundle
from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.media.frame_avatar import numpy_bgr_to_videoframe
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
_WORKER_CACHE: OrderedDict[tuple[Any, ...], "RealtimeV3Worker"] = OrderedDict()
_WORKER_CACHE_LOCK = threading.Lock()


def _worker_cache_key(
    *,
    asset_root: Path,
    template_video: Path,
    face_cache_dir: Path,
    face_cache_file: Path | None,
    device: str,
    output_transform: str,
    scale_h: float,
    scale_w: float,
    resolution: int,
    max_template_seconds: float | None,
    neck_fade_start: float,
    neck_fade_end: float,
    hubert_device: str | None,
    model_backend: str,
) -> tuple[Any, ...]:
    return (
        str(asset_root),
        str(template_video),
        str(face_cache_dir),
        str(face_cache_file) if face_cache_file else "",
        str(device),
        str(output_transform),
        float(scale_h),
        float(scale_w),
        int(resolution),
        float(max_template_seconds) if max_template_seconds is not None else None,
        float(neck_fade_start),
        float(neck_fade_end),
        str(hubert_device) if hubert_device else "",
        str(model_backend),
    )


def _env_value(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(_env_value(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


def _close_worker(worker: Any) -> None:
    close = getattr(worker, "close", None)
    if callable(close):
        close()
        return
    try:
        import gc
        import torch

        del worker
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def _enforce_worker_cache_limit() -> None:
    max_workers = _positive_int_env("OPENTALKING_QUICKTALK_WORKER_CACHE_MAX", 1)
    while len(_WORKER_CACHE) > max_workers:
        _, old_worker = _WORKER_CACHE.popitem(last=False)
        _close_worker(old_worker)


def _metadata_section(metadata: dict[str, Any], key: str) -> dict[str, Any]:
    value = metadata.get(key)
    return value if isinstance(value, dict) else {}


def _resolve_config_path(raw: str, *, base_dir: Path | None = None) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def _path_from_env_or_metadata(
    name: str,
    metadata: dict[str, Any],
    *keys: str,
    base_dir: Path | None = None,
    sections: tuple[str, ...] = (),
) -> Path:
    raw = _env_value(name)
    if not raw:
        sources: list[dict[str, Any]] = [
            section for key in sections if (section := _metadata_section(metadata, key))
        ]
        sources.append(metadata)
        for key in keys:
            for source in sources:
                value = source.get(key)
                if value:
                    raw = str(value)
                    break
            if raw:
                break
    if not raw:
        metadata_keys = [f"{section}.{key}" for section in sections for key in keys]
        metadata_keys.extend(keys)
        raise ValueError(f"Missing {name} or avatar metadata key: {', '.join(metadata_keys)}")
    return _resolve_config_path(raw, base_dir=base_dir)


def _quicktalk_template_from_bundle(bundle_path: Path) -> Path | None:
    quicktalk_dir = bundle_path / "quicktalk"
    preferred = quicktalk_dir / "template_900.mp4"
    if preferred.is_file():
        return preferred.resolve()
    if quicktalk_dir.is_dir():
        for candidate in sorted(quicktalk_dir.glob("template_*.mp4")):
            if candidate.is_file():
                return candidate.resolve()
    return None


def _optional_env_path(name: str) -> Path | None:
    raw = _env_value(name)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _quicktalk_asset_root_env() -> Path | None:
    return (
        _optional_env_path("OPENTALKING_QUICKTALK_ASSET_ROOT")
        or _optional_env_path("OPENTALKING_QUICKTALK_MODEL_ROOT")
        or _optional_env_path("OMNIRT_QUICKTALK_MODEL_ROOT")
    )


def _even(value: int) -> int:
    value = max(2, int(value))
    return value - (value % 2)


def _quicktalk_max_long_edge() -> int:
    raw = (
        _env_value("OPENTALKING_QUICKTALK_MAX_LONG_EDGE")
        or _env_value("OMNIRT_QUICKTALK_MAX_LONG_EDGE")
        or "900"
    )
    try:
        return max(0, int(raw))
    except ValueError:
        return 900


def _target_video_size(manifest: AvatarManifest) -> tuple[int, int]:
    width = int(manifest.width)
    height = int(manifest.height)
    max_long_edge = _quicktalk_max_long_edge()
    if max_long_edge > 0 and max(width, height) > max_long_edge:
        scale = max_long_edge / float(max(width, height))
        width = int(round(width * scale))
        height = int(round(height * scale))
    return _even(width), _even(height)


def _resolve_avatar_child(avatar_path: Path, raw: object, *, must_be_file: bool = False) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    path = (avatar_path / value).resolve()
    try:
        path.relative_to(avatar_path.resolve())
    except ValueError:
        return None
    if must_be_file:
        return path if path.is_file() else None
    return path if path.exists() else None


def _prepared_quicktalk_template_and_cache(
    avatar_path: Path,
    manifest: AvatarManifest,
    metadata: dict[str, Any],
) -> tuple[Path | None, Path | None]:
    quicktalk = _metadata_section(metadata, "quicktalk")
    template = _resolve_avatar_child(
        avatar_path,
        quicktalk.get("template_video") or quicktalk.get("source_video"),
        must_be_file=True,
    )
    face_cache = _resolve_avatar_child(avatar_path, quicktalk.get("face_cache"), must_be_file=True)
    if template is not None:
        return template, face_cache

    quicktalk_dir = avatar_path / "quicktalk"
    if not quicktalk_dir.is_dir():
        return None, None
    width, height = _target_video_size(manifest)
    template = quicktalk_dir / f"template_{width}x{height}.mp4"
    face_cache = quicktalk_dir / f"face_cache_v3_{width}x{height}.npz"
    if template.is_file():
        return template.resolve(), face_cache.resolve() if face_cache.is_file() else None
    return None, None


def _normalize_asset_root(asset_root: Path) -> Path:
    if (asset_root / "checkpoints").is_dir():
        return asset_root
    nested = asset_root / "hdModule"
    if (nested / "checkpoints").is_dir():
        return nested.resolve()
    return asset_root


def _validate_asset_root(asset_root: Path) -> None:
    checkpoints = asset_root / "checkpoints"
    aux_root = checkpoints / "auxiliary"
    aux_min_root = checkpoints / "auxiliary_min"
    model_files = [
        checkpoints / "quicktalk.pth",
        checkpoints / "256.onnx",
    ]
    required = [
        checkpoints / "repair.npy",
        checkpoints / "chinese-hubert-large" / "pytorch_model.bin",
    ]
    missing = [path for path in required if not path.exists()]
    if not any(path.exists() for path in model_files):
        missing.append(checkpoints / "quicktalk.pth or 256.onnx")
    if not aux_root.exists() and not aux_min_root.exists():
        missing.append(aux_root)
    if missing:
        formatted = "\n  - ".join(str(path) for path in missing)
        raise FileNotFoundError(
            "QuickTalk local assets are incomplete. "
            "OPENTALKING_QUICKTALK_ASSET_ROOT or OPENTALKING_QUICKTALK_MODEL_ROOT must point to a QuickTalk local "
            "asset directory containing checkpoints/quicktalk.pth or checkpoints/256.onnx, checkpoints/repair.npy, "
            "checkpoints/chinese-hubert-large/ and checkpoints/auxiliary/.\n"
            f"Current asset root: {asset_root}\n"
            f"Missing:\n  - {formatted}"
        )


def _explicit_cuda_available(device: str) -> bool:
    raw = (device or "").strip().lower()
    if not raw.startswith("cuda"):
        return True
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


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
        self._asset_root = _quicktalk_asset_root_env()
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
        self._model_backend = _env_value("OPENTALKING_QUICKTALK_MODEL_BACKEND", "auto")
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

    @staticmethod
    def runtime_available() -> bool:
        try:
            asset_root = _quicktalk_asset_root_env()
            if asset_root is None:
                return False
            _validate_asset_root(_normalize_asset_root(asset_root))
            device = _env_value("OPENTALKING_QUICKTALK_DEVICE") or _env_value("OPENTALKING_TORCH_DEVICE", "cuda:0")
            hubert_device = _env_value("OPENTALKING_QUICKTALK_HUBERT_DEVICE")
            return _explicit_cuda_available(device) and _explicit_cuda_available(hubert_device)
        except Exception:
            return False

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
        bundle = load_avatar_bundle(Path(avatar_path), strict=False)
        metadata = bundle.manifest.metadata or {}
        asset_root = self._asset_root if self._asset_root is not None else _path_from_env_or_metadata(
            "OPENTALKING_QUICKTALK_ASSET_ROOT",
            metadata,
            "asset_root",
            "quicktalk_asset_root",
            base_dir=bundle.path,
            sections=("quicktalk",),
        )
        asset_root = _normalize_asset_root(asset_root)
        _validate_asset_root(asset_root)
        prepared_template, face_cache_file = _prepared_quicktalk_template_and_cache(
            bundle.path,
            bundle.manifest,
            metadata,
        )
        if _env_value("OPENTALKING_QUICKTALK_TEMPLATE_VIDEO"):
            template_video = _path_from_env_or_metadata(
                "OPENTALKING_QUICKTALK_TEMPLATE_VIDEO",
                metadata,
                "template_video",
                "source_video",
                "video",
                base_dir=bundle.path,
                sections=("quicktalk",),
            )
        elif prepared_template is not None:
            template_video = prepared_template
        else:
            try:
                template_video = _path_from_env_or_metadata(
                    "OPENTALKING_QUICKTALK_TEMPLATE_VIDEO",
                    metadata,
                    "template_video",
                    "source_video",
                    "video",
                    base_dir=bundle.path,
                    sections=("quicktalk",),
                )
            except ValueError:
                bundle_template = _quicktalk_template_from_bundle(bundle.path)
                if bundle_template is None:
                    raise
                template_video = bundle_template
            if template_video is None:
                raise
        face_cache_raw = _env_value("OPENTALKING_QUICKTALK_FACE_CACHE_DIR")
        face_cache_dir = Path(face_cache_raw).expanduser().resolve() if face_cache_raw else asset_root / ".face_cache_v3"
        max_template_seconds = (
            float(self._max_template_seconds_env)
            if self._max_template_seconds_env
            else None
        )

        from opentalking.models.quicktalk.runtime import RealtimeV3Worker

        cache_key = _worker_cache_key(
            asset_root=asset_root,
            template_video=template_video,
            face_cache_dir=face_cache_dir,
            face_cache_file=face_cache_file,
            device=self._device,
            output_transform=self._output_transform,
            scale_h=self._scale_h,
            scale_w=self._scale_w,
            resolution=self._resolution,
            max_template_seconds=max_template_seconds,
            neck_fade_start=self._neck_fade_start,
            neck_fade_end=self._neck_fade_end,
            hubert_device=self._hubert_device,
            model_backend=self._model_backend,
        )

        cache_disabled = _env_value("OPENTALKING_QUICKTALK_WORKER_CACHE", "1") == "0"

        worker: RealtimeV3Worker | None = None
        if not cache_disabled:
            worker = _WORKER_CACHE.get(cache_key)
            if worker is not None:
                _WORKER_CACHE.move_to_end(cache_key)
                log.info(
                    "quicktalk worker cache HIT (avatar=%s)", bundle.manifest.id
                )

        if worker is None:
            with _WORKER_CACHE_LOCK:
                if not cache_disabled:
                    worker = _WORKER_CACHE.get(cache_key)
                    if worker is not None:
                        _WORKER_CACHE.move_to_end(cache_key)
                if worker is None:
                    log.info(
                        "quicktalk worker cache MISS — building (avatar=%s)",
                        bundle.manifest.id,
                    )
                    worker = RealtimeV3Worker(
                        asset_root=asset_root,
                        template_video=template_video,
                        face_cache_dir=face_cache_dir,
                        face_cache_file=face_cache_file,
                        device=self._device,
                        output_transform=self._output_transform,
                        scale_h=self._scale_h,
                        scale_w=self._scale_w,
                        resolution=self._resolution,
                        max_template_seconds=max_template_seconds,
                        neck_fade_start=self._neck_fade_start,
                        neck_fade_end=self._neck_fade_end,
                        hubert_device=self._hubert_device,
                        model_backend=self._model_backend,
                    )
                    if not cache_disabled:
                        _WORKER_CACHE[cache_key] = worker
                        _enforce_worker_cache_limit()

        session_state = worker.make_state()
        return QuickTalkState(
            manifest=bundle.manifest,
            worker=worker,
            fps=worker.fps,
            extra={},
            session_state=session_state,
        )

    def warmup(self, avatar_state: QuickTalkState | None = None) -> None:
        if avatar_state is None:
            return
        previous_frame_index = avatar_state.frame_index
        previous_session_state = avatar_state.session_state
        avatar_state.session_state = avatar_state.worker.make_state()
        sample_rate = 16000
        samples = max(3200, sample_rate // 4)
        silence = np.zeros(samples, dtype=np.int16)
        try:
            self.render_audio_chunk(
                avatar_state,
                AudioChunk(
                    data=silence,
                    sample_rate=sample_rate,
                    duration_ms=1000.0 * float(samples) / float(sample_rate),
                ),
            )
        finally:
            avatar_state.frame_index = previous_frame_index
            avatar_state.session_state = previous_session_state

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
