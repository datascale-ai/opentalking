"""FlashHead HTTP client for OmniRT ``/v1/generate`` audio2video services."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
import wave
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from opentalking.core.types.frames import VideoFrameData

log = logging.getLogger(__name__)


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid %s=%r, using %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid %s=%r, using %.1f", name, raw, default)
        return default


def _default_base_url() -> str:
    return _env_str("OPENTALKING_FLASHHEAD_BASE_URL", "http://8.92.7.195:8766")


def _safe_relative_remote_path(remote_path: str) -> Path | None:
    p = Path(remote_path)
    parts = [part for part in p.parts if part not in {"", "/", "."}]
    if not parts or any(part == ".." for part in parts):
        return None
    return Path(*parts)


class FlashHeadHTTPClient:
    """Small adapter that presents FlashHead HTTP generation like a FlashTalk client.

    OmniRT's current FlashHead service is synchronous HTTP rather than a streaming
    WebSocket.  This client writes each PCM chunk as a WAV file, calls
    ``POST /v1/generate`` with ``task_type=audio2video``, then decodes the returned
    MP4 artifact into BGR frames for the existing WebRTC runner.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        shared_local_dir: str | None = None,
        shared_remote_dir: str | None = None,
        output_local_dir: str | None = None,
        output_remote_dir: str | None = None,
        output_base_url: str | None = None,
        timeout_sec: float | None = None,
        fps: int | None = None,
        sample_rate: int | None = None,
        width: int | None = None,
        height: int | None = None,
        frame_num: int | None = None,
        chunk_samples: int | None = None,
    ) -> None:
        self._base_url = (base_url or _default_base_url()).rstrip("/")
        self._model = model or _env_str("OPENTALKING_FLASHHEAD_MODEL", "soulx-flashhead-1.3b")
        self._shared_local_dir = Path(
            shared_local_dir
            or _env_str("OPENTALKING_FLASHHEAD_SHARED_LOCAL_DIR", "/tmp/opentalking_flashhead_io")
        ).expanduser().resolve()
        self._shared_remote_dir = (
            shared_remote_dir
            or _env_str("OPENTALKING_FLASHHEAD_SHARED_REMOTE_DIR", str(self._shared_local_dir))
        ).rstrip("/")
        local_out = output_local_dir or _env_str("OPENTALKING_FLASHHEAD_OUTPUT_LOCAL_DIR", "")
        remote_out = output_remote_dir or _env_str("OPENTALKING_FLASHHEAD_OUTPUT_REMOTE_DIR", "")
        self._output_local_dir = Path(local_out).expanduser().resolve() if local_out else None
        self._output_remote_dir = remote_out.rstrip("/") if remote_out else None
        self._output_base_url = (
            output_base_url or _env_str("OPENTALKING_FLASHHEAD_OUTPUT_BASE_URL", "")
        ).rstrip("/")
        self._timeout_sec = timeout_sec or _env_float("OPENTALKING_FLASHHEAD_TIMEOUT_SEC", 600.0)

        self.fps = int(fps or _env_int("OPENTALKING_FLASHHEAD_FPS", 25))
        self.sample_rate = int(sample_rate or _env_int("OPENTALKING_FLASHHEAD_SAMPLE_RATE", 16000))
        self.width = int(width or _env_int("OPENTALKING_FLASHHEAD_WIDTH", 416))
        self.height = int(height or _env_int("OPENTALKING_FLASHHEAD_HEIGHT", 704))
        self.frame_num = int(frame_num or _env_int("OPENTALKING_FLASHHEAD_FRAME_NUM", self.fps))
        self.motion_frames_num = 0
        self.slice_len = self.frame_num
        default_chunk_samples = int(round(self.sample_rate * (self.frame_num / max(1, self.fps))))
        self.audio_chunk_samples = int(
            chunk_samples
            or _env_int("OPENTALKING_FLASHHEAD_CHUNK_SAMPLES", default_chunk_samples)
        )

        self._client: httpx.AsyncClient | None = None
        self._ref_image_remote_path = ""
        self._session_dir = self._shared_local_dir / f"session_{uuid.uuid4().hex[:12]}"
        self._chunk_index = 0

    async def connect(self) -> None:
        if self._client is None:
            timeout = httpx.Timeout(self._timeout_sec, connect=10.0)
            self._client = httpx.AsyncClient(timeout=timeout)
        self._shared_local_dir.mkdir(parents=True, exist_ok=True)
        self._session_dir.mkdir(parents=True, exist_ok=True)

    async def init_session(
        self,
        ref_image: bytes | str | Path,
        prompt: str = "A person is talking. Only the foreground characters are moving, the background remains static.",
        seed: int = 9999,
    ) -> dict[str, Any]:
        await self.connect()
        _ = prompt
        _ = seed

        suffix = ".png"
        if isinstance(ref_image, (str, Path)):
            src = Path(ref_image).expanduser().resolve()
            suffix = src.suffix or suffix
            dst = self._session_dir / f"reference{suffix}"
            if src != dst:
                shutil.copyfile(src, dst)
        else:
            dst = self._session_dir / f"reference{suffix}"
            dst.write_bytes(ref_image)
        self._ref_image_remote_path = self._to_remote_shared_path(dst)
        log.info(
            "FlashHead session init OK: endpoint=%s model=%s remote_ref=%s fps=%d chunk_samples=%d",
            self._base_url,
            self._model,
            self._ref_image_remote_path,
            self.fps,
            self.audio_chunk_samples,
        )
        return {
            "type": "init",
            "model": self._model,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "sample_rate": self.sample_rate,
            "frame_num": self.frame_num,
            "motion_frames_num": self.motion_frames_num,
            "slice_len": self.slice_len,
        }

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        if self._client is None:
            await self.connect()
        if not self._ref_image_remote_path:
            raise RuntimeError("FlashHead session is not initialized. Call init_session() first.")

        pcm = np.asarray(audio_pcm, dtype=np.int16).reshape(-1)
        wav_path = self._write_chunk_wav(pcm)
        remote_audio_path = self._to_remote_shared_path(wav_path)
        payload = self._build_generate_payload(remote_audio_path)

        assert self._client is not None
        t0 = time.monotonic()
        resp = await self._client.post(f"{self._base_url}/v1/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        artifact = await self._resolve_output_artifact(data)
        frames = await asyncio.to_thread(self._decode_video_file, artifact)
        log.info(
            "FlashHead HTTP chunk: frames=%d wait=%.2fs artifact=%s",
            len(frames),
            time.monotonic() - t0,
            artifact,
        )
        return frames

    async def close(self, send_close_msg: bool = True) -> None:
        _ = send_close_msg
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _write_chunk_wav(self, pcm: np.ndarray) -> Path:
        self._chunk_index += 1
        path = self._session_dir / f"chunk_{self._chunk_index:08d}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(np.asarray(pcm, dtype="<i2").tobytes())
        return path

    def _to_remote_shared_path(self, local_path: Path) -> str:
        local_path = local_path.expanduser().resolve()
        try:
            rel = local_path.relative_to(self._shared_local_dir)
        except ValueError:
            return str(local_path)
        if not self._shared_remote_dir:
            return str(local_path)
        return f"{self._shared_remote_dir}/{rel.as_posix()}"

    def _build_generate_payload(self, remote_audio_path: str) -> dict[str, Any]:
        config: dict[str, Any] = {
            "preset": _env_str("OPENTALKING_FLASHHEAD_PRESET", "balanced"),
            "fps": self.fps,
        }
        raw_config = (
            _env_str("OPENTALKING_FLASHHEAD_CONFIG_JSON", "")
            or _env_str("OPENTALKING_FLASHHEAD_PARAMETERS_JSON", "")
        )
        if raw_config:
            try:
                loaded = json.loads(raw_config)
                if isinstance(loaded, dict):
                    config.update(loaded)
            except json.JSONDecodeError:
                log.warning("Invalid OPENTALKING_FLASHHEAD_CONFIG_JSON; ignoring")

        return {
            "task": "audio2video",
            "model": self._model,
            "inputs": {
                "image": self._ref_image_remote_path,
                "audio": remote_audio_path,
            },
            "config": config,
        }

    async def _resolve_output_artifact(self, data: Any) -> Path:
        raw = self._extract_artifact_ref(data)
        if not raw:
            raise RuntimeError(f"FlashHead response does not contain a video artifact: {data!r}")
        if raw.startswith(("http://", "https://")):
            return await self._download_artifact(raw)

        path = self._map_remote_path_to_local(raw)
        if path is not None and path.is_file():
            return path

        if self._output_base_url:
            return await self._download_artifact(f"{self._output_base_url}/{raw.lstrip('/')}")
        if raw.startswith("/") and self._output_base_url:
            return await self._download_artifact(f"{self._output_base_url}{raw}")

        raise FileNotFoundError(
            "FlashHead output artifact is not readable from this host: "
            f"{raw!r}. Configure OPENTALKING_FLASHHEAD_OUTPUT_LOCAL_DIR/"
            "OPENTALKING_FLASHHEAD_OUTPUT_REMOTE_DIR or OPENTALKING_FLASHHEAD_OUTPUT_BASE_URL."
        )

    def _extract_artifact_ref(self, data: Any) -> str | None:
        candidates: list[Any] = []
        if isinstance(data, dict):
            for key in ("outputs", "artifacts", "result", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    candidates.extend(value)
                elif value is not None:
                    candidates.append(value)
        else:
            candidates.append(data)

        for item in candidates:
            ref = self._artifact_ref_from_item(item)
            if ref:
                return ref
        return None

    def _artifact_ref_from_item(self, item: Any) -> str | None:
        if isinstance(item, str):
            return item
        if not isinstance(item, dict):
            return None
        for key in ("path", "url", "uri", "file", "filename", "output_path", "video"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = item.get("artifact")
        if isinstance(nested, dict):
            return self._artifact_ref_from_item(nested)
        return None

    def _map_remote_path_to_local(self, raw: str) -> Path | None:
        remote = raw.strip()
        if not remote:
            return None
        p = Path(remote)
        if p.is_file():
            return p

        mappings: list[tuple[str, Path]] = []
        if self._output_remote_dir and self._output_local_dir is not None:
            mappings.append((self._output_remote_dir, self._output_local_dir))
        mappings.append((self._shared_remote_dir, self._shared_local_dir))

        for remote_root, local_root in mappings:
            if not remote_root:
                continue
            remote_root = remote_root.rstrip("/")
            if remote == remote_root:
                return local_root
            prefix = f"{remote_root}/"
            if remote.startswith(prefix):
                rel = remote[len(prefix):]
                return (local_root / rel).resolve()

        if self._output_local_dir is not None:
            rel = _safe_relative_remote_path(remote)
            if rel is not None:
                return (self._output_local_dir / rel).resolve()
            return (self._output_local_dir / Path(remote).name).resolve()
        return None

    async def _download_artifact(self, url: str) -> Path:
        if self._client is None:
            await self.connect()
        assert self._client is not None
        resp = await self._client.get(url)
        resp.raise_for_status()
        path = self._session_dir / f"artifact_{uuid.uuid4().hex[:10]}.mp4"
        path.write_bytes(resp.content)
        return path

    def _decode_video_file(self, path: Path) -> list[VideoFrameData]:
        import cv2

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open FlashHead output video: {path}")
        frames: list[VideoFrameData] = []
        idx = 0
        frame_ms = 1000.0 / max(1, self.fps)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(
                    VideoFrameData(
                        data=np.ascontiguousarray(frame[:, :, :3].astype(np.uint8, copy=False)),
                        width=frame.shape[1],
                        height=frame.shape[0],
                        timestamp_ms=idx * frame_ms,
                    )
                )
                idx += 1
        finally:
            cap.release()
        if not frames:
            raise RuntimeError(f"FlashHead output video contains no frames: {path}")
        return frames
