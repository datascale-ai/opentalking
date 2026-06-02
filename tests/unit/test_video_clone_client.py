from __future__ import annotations

from types import SimpleNamespace

from opentalking.providers.synthesis.omnirt import derive_video_clone_ws_url
from opentalking.providers.synthesis.video_clone.ws_client import MAGIC_FRAME, VideoCloneWSClient


def test_video_clone_url_uses_independent_omnirt_route() -> None:
    assert (
        derive_video_clone_ws_url("http://omnirt:9000", "fasterliveportrait")
        == "ws://omnirt:9000/v1/avatar/video-clone/fasterliveportrait"
    )


def test_video_clone_url_preserves_endpoint_base_path() -> None:
    assert (
        derive_video_clone_ws_url("https://gw.example.com/omnirt/", "fasterliveportrait")
        == "wss://gw.example.com/omnirt/v1/avatar/video-clone/fasterliveportrait"
    )


def test_video_clone_client_builds_frame_payload() -> None:
    assert VideoCloneWSClient.frame_payload(b"jpeg") == MAGIC_FRAME + b"jpeg"


def test_resolve_video_clone_url_prefers_explicit_setting() -> None:
    settings = SimpleNamespace(
        omnirt_endpoint="http://omnirt:9000",
        omnirt_video_clone_path_template="/v1/video2video/{model}",
    )

    assert (
        VideoCloneWSClient.resolve_url(settings)
        == "ws://omnirt:9000/v1/video2video/fasterliveportrait"
    )
