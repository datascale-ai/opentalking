from __future__ import annotations

import asyncio
import tempfile
import uuid
import wave
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import cv2
import numpy as np

from opentalking.avatar.fasterliveportrait_config import normalize_fasterliveportrait_runtime_config
from opentalking.avatar.loader import load_avatar_bundle
from opentalking.core.model_config import get_model_config
from opentalking.core.types.frames import VideoFrameData
from opentalking.export_store import create_video_export
from opentalking.models.registry import get_adapter
from opentalking.providers.stt.dashscope.adapter import decode_audio_file_to_pcm_i16
from opentalking.providers.synthesis.audio2video_client import LocalAudio2VideoClient, OmniRTAudio2VideoClient
from opentalking.providers.synthesis.flashtalk.ws_client import FlashTalkWSClient
from opentalking.providers.synthesis.omnirt import auth_headers, resolve_synthesis_ws_url
from opentalking.providers.tts.factory import build_tts_adapter

SUPPORTED_VIDEO_CREATION_MODELS = {"wav2lip", "quicktalk", "fasterliveportrait"}


def _settings_path(settings: object, name: str, default: str) -> Path:
    return Path(str(getattr(settings, name, default) or default)).expanduser().resolve()


def _settings_int(settings: object, name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _export_with_download_url(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "download_url": f"/exports/videos/{item['id']}/download"}


def _safe_title(title: str | None, *, model: str, avatar_id: str) -> str:
    value = (title or "").strip()
    return value or f"视频创作 · {model} · {avatar_id}"


def _avatar_dir(settings: object, avatar_id: str) -> Path:
    value = avatar_id.strip()
    if not value:
        raise ValueError("avatar_id is required")
    avatars_root = _settings_path(settings, "avatars_dir", "./examples/avatars")
    target = (avatars_root / value).resolve()
    try:
        target.relative_to(avatars_root)
    except ValueError as exc:
        raise ValueError("invalid avatar_id") from exc
    if not target.is_dir():
        raise FileNotFoundError("avatar not found")
    load_avatar_bundle(target, strict=False)
    return target


def _normalize_model(model: str) -> str:
    value = (model or "").strip().lower()
    if value not in SUPPORTED_VIDEO_CREATION_MODELS:
        raise ValueError("video creation only supports wav2lip, quicktalk, and fasterliveportrait")
    return value


def _reference_image_path(avatar_path: Path) -> Path:
    for name in ("reference.png", "reference.jpg", "reference.jpeg", "reference.webp", "preview.png"):
        path = avatar_path / name
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError("avatar reference image not found")


_FASTLIVEPORTRAIT_VIDEO_CONFIG_KEYS = (
    "width",
    "height",
    "fps",
    "chunk_samples",
    "emit_frames_per_chunk",
    "render_keyframes_per_chunk",
    "disable_frame_interpolation",
    "head_motion_multiplier",
    "pose_motion_multiplier",
    "yaw_multiplier",
    "pitch_multiplier",
    "roll_multiplier",
    "animation_region",
    "expression_multiplier",
    "mouth_open_multiplier",
    "mouth_corner_multiplier",
    "cheek_jaw_multiplier",
    "driving_multiplier",
    "cfg_scale",
    "cfg_cond",
    "flag_stitching",
    "flag_pasteback",
    "flag_normalize_lip",
    "flag_relative_motion",
    "flag_lip_retargeting",
    "lip_retargeting_multiplier",
    "lip_retargeting_min",
    "lip_retargeting_max",
    "lip_retargeting_noise_floor",
    "head_only_pasteback",
    "lookahead_ms",
)

VIDEO_CREATION_FASTLIVEPORTRAIT_DEFAULT_CONFIG: dict[str, object] = {
    "head_motion_multiplier": 0.3,
    "pose_motion_multiplier": 0.35,
    "yaw_multiplier": 0.85,
    "pitch_multiplier": 1.0,
    "roll_multiplier": 0.85,
    "animation_region": "lip",
    "expression_multiplier": 1.0,
    "mouth_open_multiplier": 0.9,
    "mouth_corner_multiplier": 0.85,
    "cheek_jaw_multiplier": 0.9,
    "driving_multiplier": 1.0,
    "cfg_scale": 3.0,
    "flag_stitching": True,
    "flag_pasteback": True,
    "flag_relative_motion": True,
    "flag_normalize_lip": False,
    "flag_lip_retargeting": False,
}


def _fasterliveportrait_video_config(
    raw: Mapping[str, object] | None,
) -> dict[str, object] | None:
    base = get_model_config("fasterliveportrait")
    out: dict[str, object] = {}
    for key in _FASTLIVEPORTRAIT_VIDEO_CONFIG_KEYS:
        value = base.get(key)
        if value is not None:
            out[key] = value
    out.update(VIDEO_CREATION_FASTLIVEPORTRAIT_DEFAULT_CONFIG)
    out.update(normalize_fasterliveportrait_runtime_config(dict(raw or {})))
    return out or None


def _fasterliveportrait_preroll_samples(settings: object, model: str, sample_rate: int) -> int:
    if model != "fasterliveportrait":
        return 0
    preroll_ms = _settings_int(settings, "video_creation_fasterliveportrait_preroll_ms", 400)
    if preroll_ms <= 0 or sample_rate <= 0:
        return 0
    return max(0, int(round(float(sample_rate) * float(preroll_ms) / 1000.0)))


def _audio2video_client(settings: object, model: str, sample_rate: int):
    if model == "fasterliveportrait":
        ws_url = resolve_synthesis_ws_url(model, settings)
        headers = auth_headers(settings)
        return OmniRTAudio2VideoClient(
            FlashTalkWSClient(ws_url, extra_headers=headers or None)
        )
    return LocalAudio2VideoClient(
        get_adapter(model),
        device=_device_for_model(settings, model),
        sample_rate=sample_rate,
    )


def _init_session_kwargs(
    *,
    model: str,
    avatar_path: Path,
    fasterliveportrait_config: Mapping[str, object] | None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {"avatar_path": avatar_path}
    if model != "fasterliveportrait":
        return kwargs
    kwargs["ref_image"] = _reference_image_path(avatar_path)
    video_config = _fasterliveportrait_video_config(fasterliveportrait_config)
    if video_config:
        kwargs["video_config"] = video_config
    return kwargs


def _device_for_model(settings: object, model: str) -> str:
    if model == "quicktalk":
        return str(
            getattr(settings, "quicktalk_device", "")
            or getattr(settings, "torch_device", "")
            or "cuda:0"
        )
    if model == "wav2lip":
        return str(
            getattr(settings, "wav2lip_device", "")
            or getattr(settings, "torch_device", "")
            or "cuda"
        )
    return str(getattr(settings, "torch_device", "") or "cuda")


def _frame_array(frame: VideoFrameData | Any) -> np.ndarray | None:
    data = getattr(frame, "data", frame)
    arr = np.asarray(data)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None
    return np.ascontiguousarray(arr[:, :, :3].astype(np.uint8, copy=False))


def _write_wav(path: Path, pcm: np.ndarray, sample_rate: int = 16000) -> None:
    arr = np.asarray(pcm, dtype="<i2").reshape(-1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(arr.tobytes())


def _write_video_only(path: Path, frames: list[np.ndarray], fps: float) -> None:
    if not frames:
        raise RuntimeError("video creation produced zero frames")
    first = np.asarray(frames[0], dtype=np.uint8)
    height, width = first.shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = getattr(cv2, "VideoWriter_fourcc")
    writer = cv2.VideoWriter(
        str(path),
        fourcc(*"mp4v"),
        max(1.0, float(fps)),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer: {path}")
    try:
        for frame in frames:
            arr = np.asarray(frame, dtype=np.uint8)
            if arr.shape[:2] != (height, width):
                resized = cv2.resize(arr, (width, height), interpolation=cv2.INTER_AREA)
                arr = np.asarray(resized, dtype=np.uint8)
            writer.write(arr)
    finally:
        writer.release()


async def _ffmpeg_mux(ffmpeg_bin: str, video_in: Path, audio_in: Path, out_mp4: Path) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_in),
        "-i",
        str(audio_in),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out_mp4),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"ffmpeg mux failed ({proc.returncode}): {detail}")


class VideoCreationService:
    def __init__(self, settings: object) -> None:
        self.settings = settings

    async def create_from_audio_file(
        self,
        *,
        model: str,
        avatar_id: str,
        upload_path: Path,
        title: str,
        mime_type: str | None = None,
        fasterliveportrait_config: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        pcm = await decode_audio_file_to_pcm_i16(upload_path)
        if pcm.size == 0:
            raise ValueError("audio decoded to empty PCM")
        return await self._create_from_pcm(
            model=model,
            avatar_id=avatar_id,
            pcm=pcm,
            title=title,
            source="upload",
            fasterliveportrait_config=fasterliveportrait_config,
        )

    async def create_from_tts_text(
        self,
        *,
        model: str,
        avatar_id: str,
        text: str,
        title: str,
        tts_provider: str | None,
        tts_model: str | None,
        voice: str | None,
        source: str = "tts_text",
        fasterliveportrait_config: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        text_value = text.strip()
        if not text_value:
            raise ValueError("text is required")
        sample_rate = int(getattr(self.settings, "tts_sample_rate", 16000) or 16000)
        tts = build_tts_adapter(
            sample_rate=sample_rate,
            chunk_ms=40.0,
            settings=self.settings,
            default_voice=voice,
            tts_provider=tts_provider,
            tts_model=tts_model,
        )
        chunks: list[np.ndarray] = []
        try:
            async for chunk in tts.synthesize_stream(text_value, voice=voice):
                arr = np.asarray(chunk.data, dtype=np.int16).reshape(-1)
                if arr.size:
                    chunks.append(arr.copy())
                sample_rate = int(chunk.sample_rate or sample_rate)
        finally:
            close = getattr(tts, "aclose", None)
            if close is not None:
                await close()
        if not chunks:
            raise RuntimeError("TTS returned no audio")
        pcm = np.concatenate(chunks).astype(np.int16, copy=False)
        if sample_rate != 16000:
            pcm = await self._resample_pcm(pcm, sample_rate)
        return await self._create_from_pcm(
            model=model,
            avatar_id=avatar_id,
            pcm=pcm,
            title=title,
            source=source,
            fasterliveportrait_config=fasterliveportrait_config,
        )

    async def _resample_pcm(self, pcm: np.ndarray, sample_rate: int) -> np.ndarray:
        with tempfile.TemporaryDirectory(prefix="opentalking_vc_resample_") as tmp:
            tmpdir = Path(tmp)
            src = tmpdir / "src.wav"
            out = tmpdir / "out.wav"
            _write_wav(src, pcm, sample_rate)
            proc = await asyncio.create_subprocess_exec(
                str(getattr(self.settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(out),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                detail = (stderr or b"").decode("utf-8", errors="replace")[:1200]
                raise RuntimeError(f"ffmpeg resample failed ({proc.returncode}): {detail}")
            with wave.open(str(out), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            return np.frombuffer(raw, dtype="<i2").copy()

    async def _create_from_pcm(
        self,
        *,
        model: str,
        avatar_id: str,
        pcm: np.ndarray,
        title: str,
        source: str,
        fasterliveportrait_config: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        model_value = _normalize_model(model)
        avatar_path = _avatar_dir(self.settings, avatar_id)
        job_id = uuid.uuid4().hex
        work_dir = _settings_path(self.settings, "exports_dir", "./data/exports") / "video_creation_jobs" / job_id
        work_dir.mkdir(parents=True, exist_ok=False)
        pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
        sample_rate = 16000
        audio_wav = work_dir / "audio.wav"
        _write_wav(audio_wav, pcm, sample_rate)

        client = _audio2video_client(self.settings, model_value, sample_rate)
        preroll_samples = _fasterliveportrait_preroll_samples(self.settings, model_value, sample_rate)
        render_source_pcm = pcm
        if preroll_samples:
            render_source_pcm = np.concatenate([np.zeros(preroll_samples, dtype=np.int16), pcm])

        frames: list[np.ndarray] = []
        try:
            await client.init_session(
                **_init_session_kwargs(
                    model=model_value,
                    avatar_path=avatar_path,
                    fasterliveportrait_config=fasterliveportrait_config,
                )
            )
            await client.prewarm()
            chunk_samples = max(1, int(client.audio_chunk_samples or round(sample_rate / max(1, client.fps))))
            pad_len = (-len(render_source_pcm)) % chunk_samples
            render_pcm = render_source_pcm if not pad_len else np.concatenate([
                render_source_pcm,
                np.zeros(pad_len, dtype=np.int16),
            ])
            for start in range(0, len(render_pcm), chunk_samples):
                chunk = render_pcm[start:start + chunk_samples]
                for frame in await client.generate(chunk):
                    arr = _frame_array(frame)
                    if arr is not None:
                        frames.append(arr)
            fps = float(client.fps or 25)
        finally:
            await client.close()

        if preroll_samples:
            drop_frames = max(0, int(round(float(preroll_samples) * fps / float(sample_rate))))
            if drop_frames:
                frames = frames[drop_frames:]
        target_frames = max(1, int(round(float(pcm.size) * fps / float(sample_rate))))
        if len(frames) > target_frames:
            frames = frames[:target_frames]

        video_only = work_dir / "video_only.mp4"
        _write_video_only(video_only, frames, fps)
        output_mp4 = work_dir / "result.mp4"
        await _ffmpeg_mux(str(getattr(self.settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"), video_only, audio_wav, output_mp4)
        content = output_mp4.read_bytes()
        duration = float(pcm.size) / float(sample_rate) if sample_rate else None
        item = create_video_export(
            _settings_path(self.settings, "exports_dir", "./data/exports"),
            content=content,
            mime_type="video/mp4",
            kind="video_creation",
            title=_safe_title(title, model=model_value, avatar_id=avatar_id),
            duration_sec=duration,
            session_id=None,
            avatar_id=avatar_id,
            model=model_value,
            max_bytes=_settings_int(self.settings, "export_max_bytes", 1024 * 1024 * 1024),
        )
        return {
            "job_id": job_id,
            "status": "done",
            "source": source,
            "export_video": _export_with_download_url(item),
        }
