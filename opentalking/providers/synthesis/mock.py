"""Mock synthesis adapter — returns the avatar reference image as static frames.

Used for:
  - frontend dev (no GPU available)
  - smoke testing the API/Worker/RTC pipeline without a real inference backend
  - first-run UX in `docker compose up` (default profile has no omnirt)

Activate by selecting `model=mock` in the frontend (or in the session
creation request). No environment toggle is needed.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np

from opentalking.core.registry import register

logger = logging.getLogger(__name__)


@dataclass
class MockSynthesisAdapter:
    """Echoes the reference image as a static video stream synced to audio length.

    Real models produce one frame per ~40ms of audio (25 fps). Mock matches that
    cadence so RTC pacing logic on the consumer side is exercised.
    """

    sample_rate: int = 16000
    fps: int = 25

    async def stream_audio_to_video(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        reference_image: bytes,
        params: dict | None = None,
    ) -> AsyncIterator[np.ndarray]:
        # Decode reference image to a numpy frame (best effort; if PIL is missing
        # we fall back to a 256x256 gray placeholder).
        frame = _decode_or_placeholder(reference_image)
        samples_per_frame = max(1, self.sample_rate // self.fps)
        leftover = 0

        async for chunk in audio_chunks:
            samples = len(chunk) // 2  # i16le → samples
            total = samples + leftover
            n_frames = total // samples_per_frame
            leftover = total - n_frames * samples_per_frame
            for _ in range(n_frames):
                yield frame.copy()
                # Yield to the event loop so consumers can interleave reads.
                await asyncio.sleep(0)


def _decode_or_placeholder(reference_image: bytes) -> np.ndarray:
    try:
        from PIL import Image
        from io import BytesIO

        img = Image.open(BytesIO(reference_image)).convert("RGB")
        return np.asarray(img, dtype=np.uint8)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("MockSynthesis could not decode reference image (%s); using placeholder", exc)
        return np.full((256, 256, 3), 128, dtype=np.uint8)


register("synthesis", "mock")(MockSynthesisAdapter)
