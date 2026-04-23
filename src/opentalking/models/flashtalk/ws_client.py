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

import numpy as np

try:
    import websockets
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    websockets = None  # type: ignore[assignment]

from opentalking.core.types.frames import VideoFrameData

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

    def __init__(self, ws_url: str | None = None) -> None:
        if websockets is None:
            raise RuntimeError("websockets package required: pip install websockets")
        self._ws_url = ws_url or _default_ws_url()
        self._ws = None
        # Populated after init_session
        self.frame_num: int = 0
        self.motion_frames_num: int = 0
        self.slice_len: int = 0
        self.fps: int = 25
        self.height: int = 0
        self.width: int = 0
        self.sample_rate: int = 16000
        self.audio_chunk_samples: int = 0  # slice_len * sample_rate // fps

    async def connect(self) -> None:
        self._ws = await ws_connect(
            self._ws_url,
            max_size=50 * 1024 * 1024,  # 50 MB
            open_timeout=30,
            close_timeout=10,
        )
        log.info("Connected to FlashTalk server at %s", self._ws_url)

    async def init_session(
        self,
        ref_image: bytes | str | Path,
        prompt: str = "A person is talking. Only the foreground characters are moving, the background remains static.",
        seed: int = 9999,
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

        msg = json.dumps({
            "type": "init",
            "ref_image": base64.b64encode(ref_image).decode(),
            "prompt": prompt,
            "seed": seed,
        })
        await self._ws.send(msg)
        resp = json.loads(await self._ws.recv())

        if resp.get("type") == "error":
            raise RuntimeError(f"FlashTalk init failed: {resp.get('message')}")

        self.frame_num = resp["frame_num"]
        self.motion_frames_num = resp["motion_frames_num"]
        self.slice_len = resp["slice_len"]
        self.fps = resp["fps"]
        self.height = resp["height"]
        self.width = resp["width"]
        self.audio_chunk_samples = self.slice_len * self.sample_rate // self.fps
        log.info(
            "FlashTalk session init OK: %dx%d, %d fps, slice_len=%d, chunk_samples=%d",
            self.width, self.height, self.fps, self.slice_len, self.audio_chunk_samples,
        )
        return resp

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
        payload = MAGIC_AUDIO + pcm.tobytes()
        t0 = time.monotonic()
        await self._ws.send(payload)

        resp = await self._ws.recv()
        t_recv = time.monotonic()

        # Check for JSON error response
        if isinstance(resp, str):
            msg = json.loads(resp)
            raise RuntimeError(f"FlashTalk generate error: {msg.get('message')}")

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
        log.info(
            "FlashTalk WS chunk: frames=%d payload=%dKB wait=%.2fs parse=%.3fs "
            "decode=%.3fs workers=%d",
            frame_count,
            len(resp) // 1024,
            t_recv - t0,
            t_parse - t_recv,
            t_decode - t_parse,
            JPEG_DECODE_WORKERS,
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
