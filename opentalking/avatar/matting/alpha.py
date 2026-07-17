from __future__ import annotations

from PIL import Image


def image_has_transparency(image: Image.Image) -> bool:
    if "A" not in image.getbands():
        return False
    low, high = image.getchannel("A").getextrema()
    if not isinstance(low, int | float) or not isinstance(high, int | float):
        return False
    return low < 255 or high < 255
