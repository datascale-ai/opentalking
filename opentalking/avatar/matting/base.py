from __future__ import annotations

from typing import Protocol

from PIL import Image


class MattingError(RuntimeError):
    """Raised when an avatar matting provider cannot complete."""


class AvatarMattingProvider(Protocol):
    name: str

    def remove_background(self, image: Image.Image, *, settings: object | None = None) -> Image.Image:
        """Return an image with transparent background."""
