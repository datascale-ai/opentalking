"""URL derivation for OmniRT endpoint."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from opentalking.providers.synthesis.omnirt import (
    auth_headers,
    derive_audio2video_ws_url,
    resolve_synthesis_ws_url,
)


def test_http_endpoint_becomes_ws():
    assert (
        derive_audio2video_ws_url("http://omnirt:9000", "flashtalk")
        == "ws://omnirt:9000/v1/audio2video/flashtalk"
    )


def test_https_becomes_wss():
    assert (
        derive_audio2video_ws_url("https://omnirt.example.com", "musetalk")
        == "wss://omnirt.example.com/v1/audio2video/musetalk"
    )


def test_ws_endpoint_passthrough():
    assert (
        derive_audio2video_ws_url("ws://omnirt:9000", "wav2lip")
        == "ws://omnirt:9000/v1/audio2video/wav2lip"
    )


def test_fasterliveportrait_model_url():
    assert (
        derive_audio2video_ws_url("http://omnirt:9000", "fasterliveportrait")
        == "ws://omnirt:9000/v1/audio2video/fasterliveportrait"
    )


def test_endpoint_with_basepath_preserved():
    assert (
        derive_audio2video_ws_url("http://gw.example.com/omnirt/", "flashtalk")
        == "ws://gw.example.com/omnirt/v1/audio2video/flashtalk"
    )


def test_custom_template():
    assert (
        derive_audio2video_ws_url(
            "http://omnirt:9000",
            "musetalk",
            path_template="/api/{model}/stream",
        )
        == "ws://omnirt:9000/api/musetalk/stream"
    )


def test_unsupported_scheme():
    with pytest.raises(ValueError):
        derive_audio2video_ws_url("ftp://nope", "flashtalk")


def test_resolve_prefers_omnirt():
    s = SimpleNamespace(
        omnirt_endpoint="http://omnirt:9000",
        omnirt_audio2video_path_template="/v1/avatar/{model}",
        flashtalk_ws_url="ws://legacy:8765",
    )
    assert (
        resolve_synthesis_ws_url("flashtalk", s)
        == "ws://omnirt:9000/v1/avatar/flashtalk"
    )


def test_resolve_falls_back_to_flashtalk_ws_url():
    s = SimpleNamespace(
        omnirt_endpoint="",
        omnirt_audio2video_path_template="/v1/avatar/{model}",
        flashtalk_ws_url="ws://legacy:8765",
    )
    assert resolve_synthesis_ws_url("flashtalk", s) == "ws://legacy:8765"


def test_resolve_default_when_nothing_set():
    s = SimpleNamespace(omnirt_endpoint="", flashtalk_ws_url="")
    assert resolve_synthesis_ws_url("musetalk", s).endswith("/v1/audio2video/musetalk")


def test_auth_headers_with_key():
    s = SimpleNamespace(omnirt_api_key="sk-abc")
    assert auth_headers(s) == {"Authorization": "Bearer sk-abc"}


def test_auth_headers_empty_when_unset():
    assert auth_headers(SimpleNamespace(omnirt_api_key="")) == {}
    assert auth_headers(SimpleNamespace()) == {}
