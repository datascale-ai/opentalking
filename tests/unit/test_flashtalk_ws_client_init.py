from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from opentalking.providers.synthesis.flashtalk.ws_client import FlashTalkWSClient


class FakeWebSocket:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.sent: list[str | bytes] = []
        self.responses = responses or [
            {
                "type": "init_ok",
                "frame_num": 29,
                "motion_frames_num": 1,
                "slice_len": 28,
                "fps": 25,
                "height": 704,
                "width": 416,
                "chunk_samples": 8000,
            }
        ]

    async def send(self, payload: str | bytes) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return json.dumps(self.responses.pop(0))


@pytest.mark.asyncio
async def test_init_session_sends_wav2lip_postprocess_mode_metadata(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    client = FlashTalkWSClient("ws://example.test/v1/avatar/wav2lip")
    ws = FakeWebSocket()
    client._ws = ws
    metadata = {
        "source_image_hash": "abc123",
        "animation": {"mouth_center": [0.5, 0.56], "mouth_rx": 0.06, "mouth_ry": 0.02},
    }

    await client.init_session(
        ref_image=ref,
        wav2lip_postprocess_mode="opentalking_improved",
        mouth_metadata=metadata,
        video_config={"width": 608, "height": 594, "fps": 25},
    )

    sent = json.loads(ws.sent[0])
    assert sent["type"] == "init"
    assert sent["ref_image"] == base64.b64encode(b"image-bytes").decode()
    assert sent["wav2lip_postprocess_mode"] == "opentalking_improved"
    assert sent["mouth_metadata"] == metadata
    assert sent["width"] == 608
    assert sent["height"] == 594
    assert sent["fps"] == 25


@pytest.mark.asyncio
async def test_init_session_sends_fasterliveportrait_realtime_config(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    client = FlashTalkWSClient("ws://example.test/v1/audio2video/fasterliveportrait")
    ws = FakeWebSocket()
    client._ws = ws

    await client.init_session(
        ref_image=ref,
        video_config={
            "width": 320,
            "height": 320,
            "fps": 25,
            "chunk_samples": 8000,
            "emit_frames_per_chunk": 12,
            "render_keyframes_per_chunk": 4,
            "head_motion_multiplier": 0.4,
            "pose_motion_multiplier": 0.35,
            "expression_multiplier": 1.1,
            "mouth_open_multiplier": 2.0,
            "mouth_corner_multiplier": 1.2,
            "cheek_jaw_multiplier": 0.9,
            "cfg_scale": 3.5,
            "cfg_cond": [],
            "flag_stitching": False,
            "flag_relative_motion": True,
            "flag_lip_retargeting": False,
            "disable_frame_interpolation": True,
            "head_only_pasteback": True,
            "lookahead_ms": 240,
        },
    )

    sent = json.loads(ws.sent[0])
    assert sent["chunk_samples"] == 8000
    assert sent["emit_frames_per_chunk"] == 12
    assert sent["render_keyframes_per_chunk"] == 4
    assert sent["head_motion_multiplier"] == 0.4
    assert sent["pose_motion_multiplier"] == 0.35
    assert sent["expression_multiplier"] == 1.1
    assert sent["mouth_open_multiplier"] == 2.0
    assert sent["mouth_corner_multiplier"] == 1.2
    assert sent["cheek_jaw_multiplier"] == 0.9
    assert sent["cfg_scale"] == 3.5
    assert sent["cfg_cond"] == []
    assert sent["flag_stitching"] is False
    assert sent["flag_relative_motion"] is True
    assert sent["flag_lip_retargeting"] is False
    assert sent["disable_frame_interpolation"] is True
    assert sent["head_only_pasteback"] is True
    assert sent["lookahead_ms"] == 240


@pytest.mark.asyncio
async def test_update_runtime_config_sends_fasterliveportrait_config_update() -> None:
    client = FlashTalkWSClient("ws://example.test/v1/audio2video/fasterliveportrait")
    ws = FakeWebSocket(responses=[{"type": "config_ok", "updated": {"mouth_open_multiplier": 1.8}}])
    client._ws = ws

    response = await client.update_runtime_config(
        {
            "mouth_open_multiplier": 1.8,
            "pose_motion_multiplier": 0.2,
            "yaw_multiplier": 0.7,
            "animation_region": "lip",
            "width": 999,
        }
    )

    sent = json.loads(ws.sent[0])
    assert sent == {
        "type": "config_update",
        "config": {
            "mouth_open_multiplier": 1.8,
            "pose_motion_multiplier": 0.2,
            "yaw_multiplier": 0.7,
            "animation_region": "lip",
        },
    }
    assert response == {"type": "config_ok", "updated": {"mouth_open_multiplier": 1.8}}


def test_init_session_prefers_response_chunk_samples(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    client = FlashTalkWSClient("ws://example.test/v1/audio2video/fasterliveportrait")
    ws = FakeWebSocket()
    client._ws = ws

    async def run() -> None:
        await client.init_session(
            ref_image=ref,
            video_config={"fps": 32, "emit_frames_per_chunk": 20, "chunk_samples": 8000},
        )

    import asyncio

    asyncio.run(run())

    assert client.slice_len == 28
    assert client.audio_chunk_samples == 8000


@pytest.mark.asyncio
async def test_init_session_sends_wav2lip_frame_reference_dir(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    client = FlashTalkWSClient("ws://example.test/v1/avatar/wav2lip")
    ws = FakeWebSocket()
    client._ws = ws

    await client.init_session(
        ref_image=ref,
        reference_mode="frames",
        ref_frame_dir=frame_dir,
    )

    sent = json.loads(ws.sent[0])
    assert sent["type"] == "init"
    assert sent["ref_image"] == base64.b64encode(b"image-bytes").decode()
    assert sent["reference_mode"] == "frames"
    assert sent["ref_frame_dir"] == str(frame_dir)


@pytest.mark.asyncio
async def test_init_session_sends_wav2lip_frame_metadata_path(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    metadata = tmp_path / "mouth_metadata.json"
    metadata.write_text("{}", encoding="utf-8")
    client = FlashTalkWSClient("ws://example.test/v1/avatar/wav2lip")
    ws = FakeWebSocket()
    client._ws = ws

    await client.init_session(
        ref_image=ref,
        ref_frame_metadata_path=metadata,
    )

    sent = json.loads(ws.sent[0])
    assert sent["ref_frame_metadata_path"] == str(metadata)


@pytest.mark.asyncio
async def test_init_session_sends_wav2lip_preprocessed_flag(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    client = FlashTalkWSClient("ws://example.test/v1/avatar/wav2lip")
    ws = FakeWebSocket()
    client._ws = ws

    await client.init_session(
        ref_image=ref,
        reference_mode="frames",
        preprocessed=True,
    )

    sent = json.loads(ws.sent[0])
    assert sent["preprocessed"] is True


@pytest.mark.asyncio
async def test_init_session_sends_wav2lip_prepared_cache_dir(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    cache_dir = tmp_path / "wav2lip"
    client = FlashTalkWSClient("ws://example.test/v1/avatar/wav2lip")
    ws = FakeWebSocket()
    client._ws = ws

    await client.init_session(
        ref_image=ref,
        reference_mode="frames",
        prepared_cache_dir=cache_dir,
    )

    sent = json.loads(ws.sent[0])
    assert sent["prepared_cache_dir"] == str(cache_dir)


@pytest.mark.asyncio
async def test_init_session_sends_quicktalk_template_fields(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    template_video = tmp_path / "idle.mp4"
    template_video.write_bytes(b"video-bytes")
    template_frames = tmp_path / "frames"
    template_frames.mkdir()
    client = FlashTalkWSClient("ws://example.test/v1/audio2video/quicktalk")
    ws = FakeWebSocket()
    client._ws = ws

    await client.init_session(
        ref_image=ref,
        template_mode="video",
        template_video=template_video,
        template_frame_dir=template_frames,
    )

    sent = json.loads(ws.sent[0])
    assert sent["type"] == "init"
    assert sent["template_mode"] == "video"
    assert sent["template_video"] == str(template_video)
    assert sent["template_frame_dir"] == str(template_frames)


@pytest.mark.asyncio
async def test_init_session_sends_quicktalk_face_cache(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image-bytes")
    cache = tmp_path / "quicktalk" / "face_cache_v3_900.npz"
    cache.parent.mkdir()
    cache.write_bytes(b"cache")
    client = FlashTalkWSClient("ws://example.test/v1/audio2video/quicktalk")
    ws = FakeWebSocket()
    client._ws = ws

    await client.init_session(
        ref_image=ref,
        quicktalk_face_cache=cache,
    )

    sent = json.loads(ws.sent[0])
    assert sent["quicktalk_face_cache"] == str(cache)
