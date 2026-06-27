from __future__ import annotations

from pathlib import Path

from opentalking.providers.synthesis.flashhead.http_client import FlashHeadHTTPClient


def test_flashhead_payload_matches_omnirt_schema(tmp_path: Path) -> None:
    client = FlashHeadHTTPClient(
        base_url="http://example.test",
        model="soulx-flashhead-1.3b",
        shared_local_dir=str(tmp_path / "local"),
        shared_remote_dir="/mnt/flashhead",
        fps=25,
        sample_rate=16000,
        chunk_samples=16000,
    )
    client._ref_image_remote_path = "/mnt/flashhead/reference.png"

    payload = client._build_generate_payload("/mnt/flashhead/chunk.wav")

    assert payload["task"] == "audio2video"
    assert payload["model"] == "soulx-flashhead-1.3b"
    assert payload["inputs"] == {
        "image": "/mnt/flashhead/reference.png",
        "audio": "/mnt/flashhead/chunk.wav",
    }
    assert payload["config"]["fps"] == 25


def test_flashhead_maps_shared_paths(tmp_path: Path) -> None:
    local = tmp_path / "shared"
    client = FlashHeadHTTPClient(
        base_url="http://example.test",
        shared_local_dir=str(local),
        shared_remote_dir="/mnt/shared",
    )

    mapped = client._map_remote_path_to_local("/mnt/shared/out/result.mp4")

    assert mapped == (local / "out" / "result.mp4").resolve()
