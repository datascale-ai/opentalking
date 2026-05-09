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
async def test_init_session_sends_wav2lip_enhanced_postprocessing_metadata(tmp_path: Path) -> None:
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
        enable_enhanced_postprocessing=True,
        mouth_metadata=metadata,
        video_config={"width": 608, "height": 594, "fps": 25},
    )

    sent = json.loads(ws.sent[0])
    assert sent["type"] == "init"
    assert sent["ref_image"] == base64.b64encode(b"image-bytes").decode()
    assert sent["enable_enhanced_postprocessing"] is True
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
