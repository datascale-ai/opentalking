from __future__ import annotations

import pytest

from opentalking.streaming.clock import ProgramClock


def test_program_clock_is_continuous_and_uses_fixed_ticks() -> None:
    clock = ProgramClock(fps=25, sample_rate=48_000, audio_tick_ms=20)

    video = [clock.next_video() for _ in range(3)]
    audio = [clock.next_audio_tick() for _ in range(3)]

    assert video == [0.0, 40.0, 80.0]
    assert [timestamp for timestamp, _ in audio] == [0.0, 20.0, 40.0]
    assert [samples for _, samples in audio] == [960, 960, 960]

    # A speech interrupt is not a clock reset.  The next media unit continues
    # on the same timeline.
    assert clock.next_video() == 120.0
    assert clock.next_audio_tick() == (60.0, 960)


@pytest.mark.parametrize("kwargs", [{"fps": 0}, {"sample_rate": 0}, {"audio_tick_ms": 0}])
def test_program_clock_rejects_invalid_configuration(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ProgramClock(**kwargs)

