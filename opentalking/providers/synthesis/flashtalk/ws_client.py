"""FlashTalk WebSocket client for the remote inference server."""
from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import os
import struct
import time
from pathlib import Path
from typing import Any

import numpy as np

try:
    import websockets
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    websockets = None  # type: ignore[assignment]

from opentalking.core.types.frames import VideoFrameData
from opentalking.avatar.fasterliveportrait_config import (
    normalize_fasterliveportrait_runtime_config,
)

log = logging.getLogger(__name__)

MAGIC_AUDIO = b"AUDI"
MAGIC_VIDEO = b"VIDX"


def _flashtalk_env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None:
        return value
    if name.startswith("FLASHTALK_"):
        value = os.environ.get(f"OPENTALKING_{name}")
        if value is not None:
            return value
    return default


JPEG_DECODE_WORKERS = max(1, int(_flashtalk_env("FLASHTALK_JPEG_DECODE_WORKERS", "1") or "1"))
WS_PING_INTERVAL = float(_flashtalk_env("FLASHTALK_WS_PING_INTERVAL", "20") or "20")
WS_PING_TIMEOUT = float(_flashtalk_env("FLASHTALK_WS_PING_TIMEOUT", "180") or "180")

_JPEG_DECODE_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None


def _default_ws_url() -> str:
    server_host = os.environ.get("SERVER_HOST", "localhost")
    return os.environ.get("OPENTALKING_FLASHTALK_WS_URL", f"ws://{server_host}:8765")


def _decode_jpeg(jpeg_bytes: bytes) -> np.ndarray:
    import cv2

    jpeg_buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(jpeg_buf, cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError("JPEG decoding failed")
    return bgr


class FlashTalkWSClient:
    """Async client for the FlashTalk WebSocket inference server."""

    def __init__(
        self,
        ws_url: str | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if websockets is None:
            raise RuntimeError("websockets package required: pip install websockets")
        self._ws_url = ws_url or _default_ws_url()
        self._extra_headers = dict(extra_headers or {})
        self._ws = None
        self._backend_name = self._infer_backend_name(self._ws_url)
        # Populated after init_session
        self.frame_num: int = 0
        self.motion_frames_num: int = 0
        self.slice_len: int = 0
        self.fps: int = 25
        self.height: int = 0
        self.width: int = 0
        self.sample_rate: int = 16000
        self.audio_chunk_samples: int = 0  # slice_len * sample_rate // fps

    @staticmethod
    def _infer_backend_name(ws_url: str) -> str:
        suffix = ws_url.rstrip("/").rsplit("/", 1)[-1].strip().lower()
        if suffix in {"flashtalk", "musetalk", "wav2lip", "flashhead", "mock"}:
            return suffix
        return "audio2video"

    async def connect(self) -> None:
        kwargs: dict = dict(
            max_size=50 * 1024 * 1024,  # 50 MB
            open_timeout=30,
            close_timeout=10,
            ping_interval=WS_PING_INTERVAL,
            ping_timeout=WS_PING_TIMEOUT,
        )
        if self._extra_headers:
            # websockets >= 13: prefer additional_headers; fall back to extra_headers.
            try:
                self._ws = await ws_connect(
                    self._ws_url,
                    additional_headers=self._extra_headers,
                    **kwargs,
                )
            except TypeError:
                self._ws = await ws_connect(
                    self._ws_url,
                    extra_headers=self._extra_headers,
                    **kwargs,
                )
        else:
            self._ws = await ws_connect(self._ws_url, **kwargs)
        log.info("Connected to %s server at %s", self._backend_name, self._ws_url)

    async def init_session(
        self,
        ref_image: bytes | str | Path,
        prompt: str = "A person is talking. Only the foreground characters are moving, the background remains static.",
        seed: int = 9999,
        *,
        wav2lip_postprocess_mode: str | None = None,
        mouth_metadata: dict[str, Any] | None = None,
        video_config: dict[str, Any] | None = None,
        reference_mode: str | None = None,
        ref_frame_dir: str | Path | None = None,
        ref_frame_metadata_path: str | Path | None = None,
        prepared_cache_dir: str | Path | None = None,
        preprocessed: bool | None = None,
        template_mode: str | None = None,
        template_video: str | Path | None = None,
        template_frame_dir: str | Path | None = None,
        quicktalk_face_cache: str | Path | None = None,
    ) -> dict:
        """Initialise a generation session with a reference face image.

        Parameters
        ----------
        ref_image:
            Raw PNG/JPEG bytes, or a file path to read from.
        """
        if self._ws is None:
            await self.connect()

        if isinstance(ref_image, (str, Path)):
            ref_image = Path(ref_image).read_bytes()

        payload: dict[str, Any] = {
            "type": "init",
            "ref_image": base64.b64encode(ref_image).decode(),
            "prompt": prompt,
            "seed": seed,
        }
        if wav2lip_postprocess_mode:
            payload["wav2lip_postprocess_mode"] = wav2lip_postprocess_mode
        if mouth_metadata:
            payload["mouth_metadata"] = mouth_metadata
        if reference_mode:
            payload["reference_mode"] = reference_mode
        if ref_frame_dir is not None:
            payload["ref_frame_dir"] = str(ref_frame_dir)
        if ref_frame_metadata_path is not None:
            payload["ref_frame_metadata_path"] = str(ref_frame_metadata_path)
        if prepared_cache_dir is not None:
            payload["prepared_cache_dir"] = str(prepared_cache_dir)
        if preprocessed is not None:
            payload["preprocessed"] = bool(preprocessed)
        if template_mode:
            payload["template_mode"] = template_mode
        if template_video is not None:
            payload["template_video"] = str(template_video)
        if template_frame_dir is not None:
            payload["template_frame_dir"] = str(template_frame_dir)
        if quicktalk_face_cache is not None:
            payload["quicktalk_face_cache"] = str(quicktalk_face_cache)
        if video_config:
            for key in (
                "width",
                "height",
                "fps",
                "frame_num",
                "motion_frames_num",
                "slice_len",
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
            ):
                value = video_config.get(key)
                if value is not None:
                    payload[key] = value

        msg = json.dumps(payload)
        await self._ws.send(msg)
        resp = json.loads(await self._ws.recv())

        if resp.get("type") == "error":
            raise RuntimeError(f"{self._backend_name} init failed: {resp.get('message')}")

        self.frame_num = resp["frame_num"]
        self.motion_frames_num = resp["motion_frames_num"]
        self.slice_len = resp["slice_len"]
        self.fps = resp["fps"]
        self.height = resp["height"]
        self.width = resp["width"]
        self.audio_chunk_samples = int(resp.get("chunk_samples") or (self.slice_len * self.sample_rate // self.fps))
        log.info(
            "%s session init OK: %dx%d, %d fps, slice_len=%d, chunk_samples=%d",
            self._backend_name,
            self.width, self.height, self.fps, self.slice_len, self.audio_chunk_samples,
        )
        return resp

    async def update_runtime_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if self._ws is None:
            await self.connect()
        normalized = normalize_fasterliveportrait_runtime_config(config)
        await self._ws.send(
            json.dumps(
                {
                    "type": "config_update",
                    "config": normalized,
                }
            )
        )
        resp = await self._ws.recv()
        if not isinstance(resp, str):
            raise RuntimeError("FlashTalk config update returned a binary response")
        msg = json.loads(resp)
        if msg.get("type") == "error":
            raise RuntimeError(f"FlashTalk config update failed: {msg.get('message')}")
        if msg.get("type") != "config_ok":
            raise RuntimeError(f"Unexpected FlashTalk config update response: {msg}")
        return msg

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        """Send an audio chunk and receive generated video frames.

        Parameters
        ----------
        audio_pcm:
            int16 PCM array of exactly ``audio_chunk_samples`` samples at 16 kHz.

        Returns
        -------
        list[VideoFrameData]
            Generated video frames (BGR uint8).
        """
        if self._ws is None:
            raise RuntimeError("Not connected. Call connect() first.")

        pcm = np.asarray(audio_pcm, dtype=np.int16)
        if pcm.size == 0:
            return []
        payload = MAGIC_AUDIO + pcm.tobytes()
        t0 = time.monotonic()
        await self._ws.send(payload)

        resp = await self._ws.recv()
        t_recv = time.monotonic()

        # Check for JSON error response
        if isinstance(resp, str):
            msg = json.loads(resp)
            raise RuntimeError(f"{self._backend_name} generate error: {msg.get('message')}")

        # Parse binary video response (JPEG-compressed)
        if len(resp) < 8 or resp[:4] != MAGIC_VIDEO:
            raise RuntimeError(f"Unexpected response: magic={resp[:4]!r}, len={len(resp)}")

        frame_count = struct.unpack("<I", resp[4:8])[0]

        # Decode JPEG frames: [uint32(len) + jpeg_bytes] * n_frames
        offset = 8
        jpeg_parts: list[bytes] = []
        for _ in range(frame_count):
            jpeg_len = struct.unpack("<I", resp[offset:offset + 4])[0]
            offset += 4
            jpeg_parts.append(resp[offset:offset + jpeg_len])
            offset += jpeg_len
        t_parse = time.monotonic()

        if JPEG_DECODE_WORKERS <= 1 or len(jpeg_parts) <= 1:
            bgr_frames = [_decode_jpeg(jp) for jp in jpeg_parts]
        else:
            global _JPEG_DECODE_EXECUTOR
            if _JPEG_DECODE_EXECUTOR is None:
                _JPEG_DECODE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                    max_workers=JPEG_DECODE_WORKERS,
                    thread_name_prefix="flashtalk-jpeg-decode",
                )
            bgr_frames = list(_JPEG_DECODE_EXECUTOR.map(_decode_jpeg, jpeg_parts))
        t_decode = time.monotonic()

        frames: list[VideoFrameData] = []
        for bgr in bgr_frames:
            frames.append(VideoFrameData(
                data=bgr,
                width=bgr.shape[1],
                height=bgr.shape[0],
                timestamp_ms=0.0,
            ))
        wait_s = t_recv - t0
        parse_s = t_parse - t_recv
        decode_s = t_decode - t_parse
        total_s = max(wait_s + parse_s + decode_s, 1e-6)
        log.info(
            "%s WS chunk: frames=%d payload=%dKB wait=%.2fs parse=%.3fs "
            "decode=%.3fs workers=%d fps=%.2f kb_per_frame=%.1f",
            self._backend_name,
            frame_count,
            len(resp) // 1024,
            wait_s,
            parse_s,
            decode_s,
            JPEG_DECODE_WORKERS,
            frame_count / total_s,
            (len(resp) / 1024.0) / max(1, frame_count),
        )
        return frames

    async def close(self, send_close_msg: bool = True) -> None:
        if self._ws is None:
            return
        try:
            if send_close_msg:
                await self._ws.send(json.dumps({"type": "close"}))
                resp = json.loads(await self._ws.recv())
                log.info("FlashTalk close: %s", resp.get("type"))
        except Exception:
            pass
        try:
            await self._ws.close()
        except Exception:
            pass
        self._ws = None
