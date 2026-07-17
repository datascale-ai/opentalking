from __future__ import annotations

from PIL import Image

from .alpha import image_has_transparency
from .base import AvatarMattingProvider, MattingError
from .rembg_provider import RembgMattingProvider

_PROVIDER_FACTORIES = {
    "rembg": RembgMattingProvider,
}


def resolve_avatar_matting_provider(provider_name: str) -> AvatarMattingProvider:
    key = (provider_name or "rembg").strip().lower()
    factory = _PROVIDER_FACTORIES.get(key)
    if factory is None:
        supported = ", ".join(sorted(_PROVIDER_FACTORIES))
        raise MattingError(f"unsupported avatar matting provider: {provider_name!r}; supported: {supported}")
    return factory()


def remove_avatar_background(
    image: Image.Image,
    *,
    provider_name: str = "rembg",
    settings: object | None = None,
) -> tuple[Image.Image, str]:
    provider = resolve_avatar_matting_provider(provider_name)
    return provider.remove_background(image, settings=settings), provider.name


__all__ = [
    "AvatarMattingProvider",
    "MattingError",
    "image_has_transparency",
    "remove_avatar_background",
    "resolve_avatar_matting_provider",
]
