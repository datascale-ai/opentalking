from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from opentalking.core.types.frames import VideoFrameData
from opentalking.engine import get_audio_embedding, get_base_data, get_pipeline, run_pipeline


@dataclass
class FlashTalkLocalAvatarState:
    avatar_path: Path
    prompt: str
    seed: int


class FlashTalkLocalAdapter:
    """Direct FlashTalk engine adapter for single-process local inference."""

    model_type = "flashtalk"

    def __init__(self) -> None:
        self.pipeline = None
        self.avatar_state: FlashTalkLocalAvatarState | None = None

    def load_model(
        self,
        device: str = "cuda",
        *,
        ckpt_dir: str = "./models/SoulX-FlashTalk-14B",
        wav2vec_dir: str = "./models/chinese-wav2vec2-base",
        world_size: int = 1,
    ) -> None:
        _ = device
        self.pipeline = get_pipeline(world_size=world_size, ckpt_dir=ckpt_dir, wav2vec_dir=wav2vec_dir)

    def load_avatar(self, avatar_path: str, prompt: str | None = None, seed: int = 9999) -> FlashTalkLocalAvatarState:
        path = Path(avatar_path).resolve()
        if path.is_dir():
            candidate = path / "reference.png"
            if not candidate.is_file():
                candidate = path / "reference.jpg"
            path = candidate
        if not path.is_file():
            raise FileNotFoundError(f"FlashTalk reference image not found: {path}")
        if self.pipeline is None:
            raise RuntimeError("load_model() must be called before load_avatar()")
        prompt = prompt or "A person is talking. Only the foreground characters are moving, the background remains static."
        get_base_data(self.pipeline, input_prompt=prompt, cond_image=str(path), base_seed=seed)
        self.avatar_state = FlashTalkLocalAvatarState(avatar_path=path, prompt=prompt, seed=seed)
        return self.avatar_state

    def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        if self.pipeline is None:
            raise RuntimeError("load_model() must be called before generate()")
        audio_embedding = get_audio_embedding(self.pipeline, audio_pcm)
        frames = run_pipeline(self.pipeline, audio_embedding).cpu().numpy().astype(np.uint8)
        return [
            VideoFrameData(
                data=frame[:, :, ::-1].copy(),
                width=frame.shape[1],
                height=frame.shape[0],
                timestamp_ms=0.0,
            )
            for frame in frames
        ]
