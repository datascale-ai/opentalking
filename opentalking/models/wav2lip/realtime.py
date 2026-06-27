from __future__ import annotations

# mypy: ignore-errors

from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import struct
import time
import uuid
from typing import Any, Literal

from PIL import Image

MAGIC_VIDEO = b"VIDX"

AudioFormat = Literal["pcm_s16le"]
VideoEncoding = Literal["jpeg-seq"]
ReferenceMode = Literal["image", "frames"]
TemplateMode = Literal["image", "video", "frames"]


class RealtimeAvatarError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class AvatarAudioSpec:
    format: AudioFormat = "pcm_s16le"
    sample_rate: int = 16000
    channels: int = 1
    chunk_samples: int = 17920

    @property
    def chunk_bytes(self) -> int:
        return self.chunk_samples * self.channels * 2


@dataclass
class AvatarVideoSpec:
    encoding: VideoEncoding = "jpeg-seq"
    fps: int = 25
    width: int = 416
    height: int = 704
    frame_count: int = 29
    motion_frames_num: int = 1
    slice_len: int = 28


@dataclass
class RealtimeAvatarSession:
    session_id: str
    trace_id: str
    model: str
    backend: str
    prompt: str
    image_bytes: bytes = b""
    reference_mode: ReferenceMode = "image"
    ref_frame_dir: str | None = None
    ref_frame_metadata_path: str | None = None
    prepared_cache_dir: str | None = None
    template_mode: TemplateMode = "image"
    template_video: str | None = None
    template_frame_dir: str | None = None
    quicktalk_face_cache: str | None = None
    audio: AvatarAudioSpec = field(default_factory=AvatarAudioSpec)
    video: AvatarVideoSpec = field(default_factory=AvatarVideoSpec)
    wav2lip_postprocess_mode: str = "easy_improved"
    preprocessed: bool = False
    mouth_metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    cancelled: bool = False
    created_at: float = field(default_factory=time.monotonic)


def encode_jpeg_sequence(jpeg_frames: list[bytes]) -> bytes:
    if not jpeg_frames:
        raise RealtimeAvatarError("empty_video_chunk", "At least one JPEG frame is required.")
    payload = bytearray(MAGIC_VIDEO)
    payload.extend(struct.pack("<I", len(jpeg_frames)))
    for frame in jpeg_frames:
        payload.extend(struct.pack("<I", len(frame)))
        payload.extend(frame)
    return bytes(payload)


def decode_jpeg_sequence(payload: bytes) -> list[bytes]:
    if len(payload) < 8 or payload[:4] != MAGIC_VIDEO:
        raise RealtimeAvatarError("bad_video_chunk", "Video payload must start with VIDX magic.")
    frame_count = struct.unpack("<I", payload[4:8])[0]
    if frame_count <= 0:
        raise RealtimeAvatarError("bad_video_chunk", "Video payload must contain at least one frame.")
    offset = 8
    frames: list[bytes] = []
    for _ in range(frame_count):
        if offset + 4 > len(payload):
            raise RealtimeAvatarError("bad_video_chunk", "Video payload ended before frame length.")
        frame_len = struct.unpack("<I", payload[offset : offset + 4])[0]
        offset += 4
        if frame_len <= 0 or offset + frame_len > len(payload):
            raise RealtimeAvatarError("bad_video_chunk", "Video payload contains an invalid frame length.")
        frames.append(payload[offset : offset + frame_len])
        offset += frame_len
    if offset != len(payload):
        raise RealtimeAvatarError("bad_video_chunk", "Video payload contains trailing bytes.")
    return frames


def _as_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _max_long_edge() -> int:
    raw = (
        os.environ.get("OPENTALKING_WAV2LIP_MAX_LONG_EDGE")
        or os.environ.get("OMNIRT_WAV2LIP_MAX_LONG_EDGE")
        or "0"
    ).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _scale_video_to_max_long_edge(video: AvatarVideoSpec) -> AvatarVideoSpec:
    max_long_edge = _max_long_edge()
    if max_long_edge <= 0:
        return video
    long_edge = max(video.width, video.height)
    if long_edge <= max_long_edge:
        return video
    scale = max_long_edge / float(long_edge)
    width = max(2, int(round(video.width * scale)))
    height = max(2, int(round(video.height * scale)))
    width -= width % 2
    height -= height % 2
    return AvatarVideoSpec(
        fps=video.fps,
        width=width,
        height=height,
        frame_count=video.frame_count,
        motion_frames_num=video.motion_frames_num,
        slice_len=video.slice_len,
    )


def _parse_wav2lip_postprocess_mode(raw: object) -> str:
    allowed = {"basic", "opentalking_improved", "easy_improved", "easy_enhanced"}
    if raw is None:
        return "easy_improved"
    mode = str(raw).strip().lower().replace("-", "_")
    return mode if mode in allowed else "easy_improved"


class RealtimeAvatarService:
    def __init__(self, *, runtime: Any | None = None, allowed_frame_roots: list[str | Path] | None = None) -> None:
        self.runtime = runtime
        self._sessions: dict[str, RealtimeAvatarSession] = {}
        self._allowed_frame_roots = tuple(
            Path(root).expanduser().resolve()
            for root in (allowed_frame_roots or [])
            if str(root).strip()
        )

    def create_session(
        self,
        *,
        model: str,
        backend: str = "auto",
        image_bytes: bytes,
        prompt: str = "",
        config: dict[str, object] | None = None,
    ) -> RealtimeAvatarSession:
        if not image_bytes:
            raise RealtimeAvatarError("missing_image", "A reference image is required.")
        config = dict(config or {})
        reference_mode = str(config.get("reference_mode") or "image").strip().lower()
        if reference_mode not in {"image", "frames"}:
            raise RealtimeAvatarError("bad_reference_mode", "reference_mode must be 'image' or 'frames'.")

        ref_frame_dir_str = self._optional_allowed_path(
            config.get("ref_frame_dir"),
            code="bad_frame_dir",
            label="ref_frame_dir",
            must_be_dir=True,
            required=reference_mode == "frames",
        )
        ref_frame_metadata_path_str = self._optional_allowed_path(
            config.get("ref_frame_metadata_path"),
            code="bad_frame_metadata",
            label="ref_frame_metadata_path",
            must_be_dir=False,
        )
        prepared_cache_dir_str = self._optional_allowed_path(
            config.get("prepared_cache_dir"),
            code="bad_prepared_cache_dir",
            label="prepared_cache_dir",
            must_be_dir=False,
            allow_missing_leaf=True,
        )
        sample_rate = int(config.get("sample_rate", 16000))
        video = _scale_video_to_max_long_edge(
            AvatarVideoSpec(
                fps=int(config.get("fps", 25)),
                width=int(config.get("width", 416)),
                height=int(config.get("height", 704)),
                frame_count=int(config.get("frame_num", 29)),
                motion_frames_num=int(config.get("motion_frames_num", 1)),
                slice_len=int(config.get("slice_len", 28)),
            )
        )
        mouth_metadata = config.get("mouth_metadata") or {}
        if not isinstance(mouth_metadata, dict):
            raise RealtimeAvatarError("bad_mouth_metadata", "mouth_metadata must be an object.")
        preprocessed = _as_bool(config.get("preprocessed"), default=False)
        if preprocessed and reference_mode == "frames" and not ref_frame_metadata_path_str:
            raise RealtimeAvatarError(
                "preprocessed_asset_invalid",
                "preprocessed frame references require ref_frame_metadata_path.",
            )
        session = RealtimeAvatarSession(
            session_id=f"avt_{uuid.uuid4().hex}",
            trace_id=f"trace_{uuid.uuid4().hex}",
            model=model,
            backend=backend,
            prompt=prompt,
            image_bytes=image_bytes,
            reference_mode=reference_mode,  # type: ignore[arg-type]
            ref_frame_dir=ref_frame_dir_str,
            ref_frame_metadata_path=ref_frame_metadata_path_str,
            prepared_cache_dir=prepared_cache_dir_str,
            audio=AvatarAudioSpec(
                sample_rate=sample_rate,
                channels=int(config.get("channels", 1)),
                chunk_samples=int(config.get("chunk_samples", video.slice_len * sample_rate // video.fps)),
            ),
            video=video,
            wav2lip_postprocess_mode=_parse_wav2lip_postprocess_mode(
                config.get("wav2lip_postprocess_mode")
                or os.getenv("OPENTALKING_WAV2LIP_POSTPROCESS_MODE")
            ),
            preprocessed=preprocessed,
            mouth_metadata=mouth_metadata,
        )
        self._sessions[session.session_id] = session
        return session

    def _optional_allowed_path(
        self,
        raw: object,
        *,
        code: str,
        label: str,
        must_be_dir: bool,
        required: bool = False,
        allow_missing_leaf: bool = False,
    ) -> str | None:
        value = str(raw).strip() if raw is not None else ""
        if not value:
            if required:
                raise RealtimeAvatarError(code, f"{label} is required.")
            return None
        path = Path(value).expanduser().resolve()
        if not self._allowed_frame_roots:
            raise RealtimeAvatarError(code, f"{label} requires configured allowed frame roots.")
        if not any(path == root or root in path.parents for root in self._allowed_frame_roots):
            raise RealtimeAvatarError(code, f"{label} is outside allowed frame roots.")
        if must_be_dir and not path.is_dir():
            raise RealtimeAvatarError(code, f"{label} not found.")
        if not must_be_dir and not allow_missing_leaf and not path.is_file():
            raise RealtimeAvatarError(code, f"{label} not found.")
        if not must_be_dir and allow_missing_leaf:
            existing = path if path.exists() else path.parent
            if not existing.exists():
                raise RealtimeAvatarError(code, f"{label} parent not found.")
        return str(path)

    def push_audio_chunk(self, session_id: str, pcm_s16le: bytes) -> tuple[bytes, dict[str, object]]:
        session = self._sessions[session_id]
        started = time.monotonic()
        video_payload = self.runtime.render_chunk(session, pcm_s16le)
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
        session.chunk_index += 1
        return video_payload, {
            "type": "metrics",
            "chunk_index": session.chunk_index,
            "infer_ms": elapsed_ms,
            "encode_ms": 0,
        }


class FakeRealtimeAvatarRuntime:
    def render_chunk(self, session: RealtimeAvatarSession, pcm_s16le: bytes) -> bytes:
        image = Image.new("RGB", (session.video.width, session.video.height), (len(pcm_s16le) % 255, 8, 4))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return encode_jpeg_sequence([buffer.getvalue()])
