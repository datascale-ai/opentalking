from __future__ import annotations

import pytest

from opentalking.core.registry import (
    RegistryError,
    _reset_for_tests,
    list_keys,
    register,
    resolve,
)


@pytest.fixture(autouse=True)
def _reset():
    yield
    _reset_for_tests()


def test_register_and_resolve():
    @register("tts", "fake-vendor")
    class FakeTTS:
        kind = "tts-fake"

    cls = resolve("tts", "fake-vendor")
    assert cls is FakeTTS


def test_list_keys():
    @register("stt", "alpha")
    class A: ...

    @register("stt", "beta")
    class B: ...

    keys = list_keys("stt")
    assert "alpha" in keys
    assert "beta" in keys


def test_unknown_capability_raises():
    with pytest.raises(RegistryError):
        resolve("nonexistent", "x")


def test_duplicate_registration_raises():
    @register("llm", "dup")
    class L1: ...

    with pytest.raises(RegistryError):

        @register("llm", "dup")
        class L2: ...
