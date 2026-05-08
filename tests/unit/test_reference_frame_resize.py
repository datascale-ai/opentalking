from __future__ import annotations

import numpy as np
from PIL import Image

from opentalking.media.frame_avatar import resize_reference_image_to_video


def test_reference_resize_matches_video_dimensions_without_letterbox() -> None:
    image = Image.new("RGB", (100, 50), (255, 255, 255))
    resized = resize_reference_image_to_video(image, width=80, height=80)

    assert resized.size == (80, 80)
    arr = np.asarray(resized)
    assert arr[0, 0].tolist() == [255, 255, 255]
