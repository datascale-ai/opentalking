from __future__ import annotations

import pytest

from opentalking.models.wav2lip.loader import _resolve_torch_device


class _FakeCuda:
    @staticmethod
    def is_available() -> bool:
        return False


class _FakeTorch:
    cuda = _FakeCuda()


def test_explicit_cuda_device_does_not_fall_back_to_cpu() -> None:
    with pytest.raises(RuntimeError, match="CUDA was explicitly requested"):
        _resolve_torch_device(_FakeTorch, "cuda:6")
