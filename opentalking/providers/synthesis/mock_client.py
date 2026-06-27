"""MockFlashTalkClient — drop-in replacement for FlashTalkWSClient.

Has the same surface (connect / init_session / generate / close) so the
existing FlashTalkRunner orchestration runs unchanged. Visually it just echoes
the avatar reference image as static frames at 25 fps.

Used by:
- Path 1 quick experience (frontend selects `model=mock`)
- Frontend dev / smoke tests (no GPU, no omnirt)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class VideoFrameData:
    """Mirrors the dataclass FlashTalkRunner consumes from the real WS client."""

    data: np.ndarray  # BGR uint8
    width: int
    height: int
    timestamp_ms: float


class MockFlashTalkClient:
    """Returns the reference image as a video stream synced to audio."""

    def __init__(self, ws_url: str | None = None) -> None:
        # ws_url accepted for signature compatibility; ignored.
        self._frame_bgr: np.ndarray | None = None
        # Match real FlashTalk session attributes; values are conservative defaults
        # that work with the runner's chunk pacing logic.
        self.frame_num: int = 25
        self.motion_frames_num: int = 5
        self.slice_len: int = 12
        self.fps: int = 25
        self.height: int = 256
        self.width: int = 256
        self.sample_rate: int = 16000
        self.audio_chunk_samples: int = self.slice_len * self.sample_rate // self.fps

    async def connect(self) -> None:
        return None

    async def init_session(
        self,
        ref_image: bytes | str | Path,
        prompt: str = "",
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
        del prompt, seed, wav2lip_postprocess_mode, mouth_metadata
        del reference_mode, ref_frame_dir, ref_frame_metadata_path, prepared_cache_dir, preprocessed
        del template_mode, template_video, template_frame_dir, quicktalk_face_cache
        if isinstance(ref_image, (str, Path)):
            ref_image = Path(ref_image).read_bytes()
        bgr = _decode_to_bgr(ref_image)
        if video_config:
            self.frame_num = int(video_config.get("frame_num") or self.frame_num)
            self.motion_frames_num = int(video_config.get("motion_frames_num") or self.motion_frames_num)
            self.slice_len = int(video_config.get("slice_len") or self.slice_len)
            self.fps = int(video_config.get("fps") or self.fps)
        # Round to even dims (some encoders/streamers prefer this).
        h, w = bgr.shape[:2]
        h -= h % 2
        w -= w % 2
        self._frame_bgr = np.ascontiguousarray(bgr[:h, :w])
        self.height = h
        self.width = w
        self.audio_chunk_samples = self.slice_len * self.sample_rate // self.fps
        log.info(
            "MockFlashTalk session init OK: %dx%d, %d fps, slice_len=%d, chunk_samples=%d",
            self.width, self.height, self.fps, self.slice_len, self.audio_chunk_samples,
        )
        return {
            "frame_num": self.frame_num,
            "motion_frames_num": self.motion_frames_num,
            "slice_len": self.slice_len,
            "fps": self.fps,
            "height": self.height,
            "width": self.width,
        }

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        if self._frame_bgr is None:
            raise RuntimeError("init_session() must be called before generate()")
        return [
            VideoFrameData(
                data=self._frame_bgr,
                width=self.width,
                height=self.height,
                timestamp_ms=0.0,
            )
            for _ in range(self.slice_len)
        ]

    async def close(self, send_close_msg: bool = True) -> None:
        self._frame_bgr = None


def _decode_to_bgr(image_bytes: bytes) -> np.ndarray:
    try:
        from PIL import Image

        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        rgb = np.asarray(img, dtype=np.uint8)
        # FlashTalkRunner expects BGR (mirrors WS client's cv2 path)
        return rgb[:, :, ::-1].copy()
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("MockFlashTalk could not decode reference image (%s); using gray", exc)
        return np.full((256, 256, 3), 128, dtype=np.uint8)
