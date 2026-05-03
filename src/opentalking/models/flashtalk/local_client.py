from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import numpy as np

from opentalking.core.types.frames import VideoFrameData
from opentalking.models.flashtalk.local_adapter import FlashTalkLocalAdapter


class FlashTalkLocalClient:
    """Async-compatible wrapper around the in-process FlashTalk engine."""

    def __init__(
        self,
        *,
        ckpt_dir: str,
        wav2vec_dir: str,
        device: str = "auto",
        world_size: int = 1,
        frame_num: int = 33,
        motion_frames_num: int = 5,
        fps: int = 25,
        height: int = 768,
        width: int = 448,
        sample_rate: int = 16000,
    ) -> None:
        self._adapter = FlashTalkLocalAdapter()
        self._ckpt_dir = ckpt_dir
        self._wav2vec_dir = wav2vec_dir
        self._device = device
        self._world_size = world_size
        self._loaded = False
        self._avatar_loaded = False
        self._temp_ref_image: Path | None = None

        self.frame_num = frame_num
        self.motion_frames_num = motion_frames_num
        self.slice_len = frame_num - motion_frames_num
        self.fps = fps
        self.height = height
        self.width = width
        self.sample_rate = sample_rate
        self.audio_chunk_samples = self.slice_len * self.sample_rate // self.fps

    async def connect(self) -> None:
        if self._loaded:
            return
        await asyncio.to_thread(self._load_model)

    def _load_model(self) -> None:
        ckpt_dir = Path(self._ckpt_dir).expanduser().resolve()
        wav2vec_dir = Path(self._wav2vec_dir).expanduser().resolve()
        if not ckpt_dir.exists():
            raise FileNotFoundError(
                f"FlashTalk checkpoint directory not found: {ckpt_dir}. "
                "Download the model first or switch OPENTALKING_FLASHTALK_MODE=off."
            )
        if not wav2vec_dir.exists():
            raise FileNotFoundError(
                f"FlashTalk wav2vec directory not found: {wav2vec_dir}. "
                "Download the wav2vec model first or switch OPENTALKING_FLASHTALK_MODE=off."
            )
        self._adapter.load_model(
            device=self._device,
            ckpt_dir=str(ckpt_dir),
            wav2vec_dir=str(wav2vec_dir),
            world_size=self._world_size,
        )
        self._loaded = True

    async def init_session(
        self,
        ref_image: bytes | str | Path,
        prompt: str = "A person is talking. Only the foreground characters are moving, the background remains static.",
        seed: int = 9999,
    ) -> dict[str, int | str]:
        await self.connect()
        ref_path = await asyncio.to_thread(self._prepare_ref_image, ref_image)
        await asyncio.to_thread(self._adapter.load_avatar, str(ref_path), prompt, seed)
        self._avatar_loaded = True
        return {
            "type": "init_ok",
            "frame_num": self.frame_num,
            "motion_frames_num": self.motion_frames_num,
            "slice_len": self.slice_len,
            "fps": self.fps,
            "height": self.height,
            "width": self.width,
        }

    def _prepare_ref_image(self, ref_image: bytes | str | Path) -> Path:
        if isinstance(ref_image, (str, Path)):
            return Path(ref_image).expanduser().resolve()

        fd, temp_path = tempfile.mkstemp(suffix=".png")
        temp_file = Path(temp_path)
        os.close(fd)
        with temp_file.open("wb") as handle:
            handle.write(ref_image)
        temp_file.chmod(0o600)
        if self._temp_ref_image and self._temp_ref_image.exists():
            self._temp_ref_image.unlink(missing_ok=True)
        self._temp_ref_image = temp_file
        return temp_file

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        if not self._avatar_loaded:
            raise RuntimeError("Not connected. Call init_session() first.")
        pcm = np.asarray(audio_pcm, dtype=np.int16)
        return await asyncio.to_thread(self._adapter.generate, pcm)

    async def close(self) -> None:
        self._avatar_loaded = False
        if self._temp_ref_image and self._temp_ref_image.exists():
            self._temp_ref_image.unlink(missing_ok=True)
        self._temp_ref_image = None
