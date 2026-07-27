from __future__ import annotations

import numpy as np

from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner, _LoopingIdleVideo


def test_quicktalk_idle_video_uses_the_full_source_duration_before_repeating() -> None:
    idle_video = object.__new__(_LoopingIdleVideo)
    idle_video.source_fps = 24.0
    idle_video.output_fps = 25.0
    idle_video.frame_count = 241

    assert [idle_video.source_index_for_output(index) for index in (0, 1, 250, 251, 252)] == [
        0,
        0,
        240,
        240,
        0,
    ]


def test_dynamic_idle_frames_are_configured_for_forward_looping() -> None:
    runner = object.__new__(FlashTalkRunner)
    frames = [np.zeros((2, 2, 3), dtype=np.uint8) for _ in range(3)]

    runner._set_idle_frames(frames, playback_mode="loop")

    assert runner._idle_playback_indices == [0, 1, 2]
