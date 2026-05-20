from __future__ import annotations

from pathlib import Path

from PIL import Image

from opentalking.providers.synthesis.mock_client import MockFlashTalkClient


async def test_mock_flashtalk_client_accepts_audio2video_init_metadata(tmp_path: Path) -> None:
    ref = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (128, 160, 192)).save(ref)

    client = MockFlashTalkClient()

    response = await client.init_session(
        ref_image=ref,
        wav2lip_postprocess_mode="opentalking_improved",
        mouth_metadata={"mouth_center": [16, 20]},
        video_config={"fps": 25, "width": 32, "height": 32},
        reference_mode="frames",
        ref_frame_dir=tmp_path,
        ref_frame_metadata_path=tmp_path / "metadata.json",
        prepared_cache_dir=tmp_path / "wav2lip",
        preprocessed=True,
    )

    assert response["width"] == 32
    assert response["height"] == 32
