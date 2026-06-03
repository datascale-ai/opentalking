from __future__ import annotations

import asyncio
import io
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from opentalking.avatar.loader import load_avatar_bundle
from opentalking.core.types.frames import VideoFrameData
from opentalking.export_store import create_video_export
from opentalking.models.registry import get_adapter
from opentalking.providers.stt.dashscope.adapter import decode_audio_file_to_pcm_i16
from opentalking.providers.synthesis.audio2video_client import LocalAudio2VideoClient
from opentalking.providers.tts.factory import build_tts_adapter

SUPPORTED_VIDEO_CREATION_MODELS = {"wav2lip", "quicktalk"}


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
        raise ValueError("video creation only supports wav2lip and quicktalk")
    return value


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
            source="tts_text",
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

        client = LocalAudio2VideoClient(get_adapter(model_value), device=_device_for_model(self.settings, model_value), sample_rate=sample_rate)
        frames: list[np.ndarray] = []
        try:
            await client.init_session(avatar_path=avatar_path)
            await client.prewarm()
            chunk_samples = max(1, int(client.audio_chunk_samples or round(sample_rate / max(1, client.fps))))
            pad_len = (-len(pcm)) % chunk_samples
            render_pcm = pcm if not pad_len else np.concatenate([pcm, np.zeros(pad_len, dtype=np.int16)])
            for start in range(0, len(render_pcm), chunk_samples):
                chunk = render_pcm[start:start + chunk_samples]
                for frame in await client.generate(chunk):
                    arr = _frame_array(frame)
                    if arr is not None:
                        frames.append(arr)
            fps = float(client.fps or 25)
        finally:
            await client.close()

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
