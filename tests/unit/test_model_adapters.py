from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from opentalking.core.types.frames import AudioChunk
from opentalking.models import get_adapter
from opentalking.worker.pipeline.render_pipeline import render_audio_chunk_sync


@pytest.mark.parametrize(
    ("model_type", "avatar_id"),
    [
        ("wav2lip", "demo-avatar"),
        ("musetalk", "demo-musetalk"),
    ],
)
def test_builtin_model_adapter_smoke_renders_demo_avatar(
    monkeypatch: pytest.MonkeyPatch,
    model_type: str,
    avatar_id: str,
) -> None:
    monkeypatch.setenv("OPENTALKING_WAV2LIP_USE_NEURAL", "0")
    monkeypatch.setenv("OPENTALKING_MODELS_DIR", "/tmp/opentalking-test-no-models")

    root = Path(__file__).resolve().parents[2]
    adapter = get_adapter(model_type)
    adapter.load_model("cpu")
    avatar_state = adapter.load_avatar(str(root / "examples" / "avatars" / avatar_id))
    adapter.warmup()

    sample_rate = int(avatar_state.manifest.sample_rate)
    samples = int(sample_rate * 0.2)
    t = np.arange(samples, dtype=np.float32) / sample_rate
    pcm = (np.sin(2.0 * np.pi * 220.0 * t) * 1800.0).astype(np.int16)
    chunk = AudioChunk(
        data=pcm,
        sample_rate=sample_rate,
        duration_ms=1000.0 * samples / sample_rate,
    )

    next_frame_idx, frames = render_audio_chunk_sync(
        adapter,
        avatar_state,
        chunk,
        frame_index_start=0,
        speech_frame_index_start=0,
    )

    assert next_frame_idx > 0
    assert frames
    assert frames[0].width == avatar_state.manifest.width
    assert frames[0].height == avatar_state.manifest.height
    assert frames[0].data.shape[:2] == (
        avatar_state.manifest.height,
        avatar_state.manifest.width,
    )
    assert frames[0].data.ndim == 3
    assert frames[0].data.shape[2] == 3
