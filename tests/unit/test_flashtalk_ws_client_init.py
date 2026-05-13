from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from opentalking.providers.synthesis.flashtalk.ws_client import FlashTalkWSClient


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []

    async def send(self, payload: str | bytes) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return json.dumps(
            {
                "type": "init_ok",
                "frame_num": 29,
                "motion_frames_num": 1,
                "slice_len": 28,
                "fps": 25,
                "height": 704,
                "width": 416,
            }
        )


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
