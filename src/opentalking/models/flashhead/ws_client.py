"""FlashHead realtime WebSocket client for OmniRT avatar sessions."""
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
from opentalking.models.flashtalk.ws_client import MAGIC_AUDIO, MAGIC_VIDEO

log = logging.getLogger(__name__)

JPEG_DECODE_WORKERS = max(
    1,
    int(
        os.environ.get(
            "OPENTALKING_FLASHHEAD_JPEG_DECODE_WORKERS",
            os.environ.get("OPENTALKING_FLASHTALK_JPEG_DECODE_WORKERS", "1"),
        )
        or "1"
    ),
)

_JPEG_DECODE_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None


def _default_ws_url() -> str:
    return os.environ.get(
        "OPENTALKING_FLASHHEAD_WS_URL",
        "ws://8.92.7.195:8766/v1/avatar/realtime",
    )


def _decode_jpeg(jpeg_bytes: bytes) -> np.ndarray:
    import cv2

    jpeg_buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(jpeg_buf, cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError("JPEG decoding failed")
    return bgr


class FlashHeadWSClient:
    """Async client for OmniRT's native FlashHead realtime avatar protocol."""

    def __init__(
        self,
        ws_url: str | None = None,
        *,
        model: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        if websockets is None:
            raise RuntimeError("websockets package required: pip install websockets")
        self._ws_url = ws_url or _default_ws_url()
        self._model = model or os.environ.get("OPENTALKING_FLASHHEAD_MODEL", "soulx-flashhead-1.3b")
        self._config = dict(config or {})
        self._ws = None
        self._session_id = ""

        self.frame_num: int = 0
        self.motion_frames_num: int = 0
        self.slice_len: int = 0
        self.fps: int = 25
        self.height: int = 0
        self.width: int = 0
        self.sample_rate: int = 16000
        self.audio_chunk_samples: int = 0

    async def connect(self) -> None:
        self._ws = await ws_connect(
            self._ws_url,
            max_size=50 * 1024 * 1024,
            open_timeout=30,
            close_timeout=10,
        )
        log.info("Connected to FlashHead server at %s", self._ws_url)

    async def init_session(
        self,
        ref_image: bytes | str | Path,
        prompt: str = "A person is talking. Only the foreground characters are moving, the background remains static.",
        seed: int = 9999,
    ) -> dict[str, Any]:
        if self._ws is None:
            await self.connect()

        if isinstance(ref_image, (str, Path)):
            ref_bytes = Path(ref_image).read_bytes()
        else:
            ref_bytes = ref_image

        config = {"seed": seed, **self._config}
        msg = {
            "type": "session.create",
            "model": self._model,
            "inputs": {
                "image_b64": base64.b64encode(ref_bytes).decode("ascii"),
                "prompt": prompt,
            },
            "config": config,
        }
        assert self._ws is not None
        await self._ws.send(json.dumps(msg, ensure_ascii=False))
        resp = json.loads(await self._ws.recv())
        if resp.get("type") == "error":
            raise RuntimeError(f"FlashHead init failed: {resp.get('message')}")
        if resp.get("type") != "session.created":
            raise RuntimeError(f"Unexpected FlashHead init response: {resp!r}")

        self._session_id = str(resp.get("session_id") or "")
        audio = dict(resp.get("audio") or {})
        video = dict(resp.get("video") or {})
        self.sample_rate = int(audio.get("sample_rate") or self.sample_rate)
        self.audio_chunk_samples = int(audio.get("chunk_samples") or self.audio_chunk_samples or 0)
        self.fps = int(video.get("fps") or self.fps)
        self.width = int(video.get("width") or self.width or 0)
        self.height = int(video.get("height") or self.height or 0)
        self.slice_len = int(round(self.audio_chunk_samples * self.fps / max(1, self.sample_rate)))
        self.frame_num = int(video.get("frame_count") or self.slice_len)
        self.motion_frames_num = int(video.get("motion_frames_num") or max(0, self.frame_num - self.slice_len))
        log.info(
            "FlashHead session init OK: session=%s %dx%d fps=%d chunk_samples=%d",
            self._session_id,
            self.width,
            self.height,
            self.fps,
            self.audio_chunk_samples,
        )
        return resp

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        if self._ws is None:
            raise RuntimeError("Not connected. Call connect() first.")
        pcm = np.asarray(audio_pcm, dtype=np.int16).reshape(-1)
        payload = MAGIC_AUDIO + pcm.tobytes()
        t0 = time.monotonic()
        await self._ws.send(payload)

        resp = await self._recv_video_payload()
        t_recv = time.monotonic()
        frame_count = struct.unpack("<I", resp[4:8])[0]

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
                    thread_name_prefix="flashhead-jpeg-decode",
                )
            bgr_frames = list(_JPEG_DECODE_EXECUTOR.map(_decode_jpeg, jpeg_parts))
        t_decode = time.monotonic()

        frames = [
            VideoFrameData(
                data=bgr,
                width=bgr.shape[1],
                height=bgr.shape[0],
                timestamp_ms=0.0,
            )
            for bgr in bgr_frames
        ]
        log.info(
            "FlashHead WS chunk: frames=%d payload=%dKB wait=%.2fs parse=%.3fs decode=%.3fs workers=%d",
            frame_count,
            len(resp) // 1024,
            t_recv - t0,
            t_parse - t_recv,
            t_decode - t_parse,
            JPEG_DECODE_WORKERS,
        )
        return frames

    async def _recv_video_payload(self) -> bytes:
        assert self._ws is not None
        while True:
            resp = await self._ws.recv()
            if isinstance(resp, str):
                msg = json.loads(resp)
                if msg.get("type") == "metrics":
                    continue
                if msg.get("type") == "error":
                    raise RuntimeError(f"FlashHead generate error: {msg.get('message')}")
                continue
            if len(resp) < 8 or resp[:4] != MAGIC_VIDEO:
                raise RuntimeError(f"Unexpected response: magic={resp[:4]!r}, len={len(resp)}")
            return resp

    async def close(self, send_close_msg: bool = True) -> None:
        if self._ws is None:
            return
        try:
            if send_close_msg:
                await self._ws.send(json.dumps({"type": "session.close"}))
                resp = json.loads(await self._ws.recv())
                log.info("FlashHead close: %s", resp.get("type"))
        except Exception:
            pass
        try:
            await self._ws.close()
        except Exception:
            pass
        self._ws = None
        self._session_id = ""
