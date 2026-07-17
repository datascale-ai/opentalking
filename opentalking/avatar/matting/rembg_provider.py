from __future__ import annotations

import os
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Iterator

from PIL import Image

from .base import MattingError

REMBG_U2NET_MODEL_MD5 = "60024c5c889badc19c04ad937298a77b"
REMBG_U2NET_MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"


def _configured_model_path(settings: object | None) -> Path | None:
    value = str(getattr(settings, "avatar_matting_model_path", "") or "").strip()
    return Path(value).expanduser() if value else None


def _missing_model_message() -> str:
    return (
        "未找到抠除背景模型 u2net.onnx。\n"
        f"请下载模型：{REMBG_U2NET_MODEL_URL}\n"
        "然后在 .env 中配置 OPENTALKING_AVATAR_MATTING_MODEL_PATH。"
    )


def _validate_model_path(settings: object | None) -> Path:
    model_path = _configured_model_path(settings)
    if model_path is None or not model_path.is_file():
        raise MattingError(_missing_model_message())
    if model_path.name != "u2net.onnx":
        raise MattingError("OPENTALKING_AVATAR_MATTING_MODEL_PATH 必须指向 u2net.onnx 文件。")
    return model_path.resolve()


@contextmanager
def _u2net_home_for_model(model_path: Path) -> Iterator[None]:
    previous = os.environ.get("U2NET_HOME")
    os.environ["U2NET_HOME"] = str(model_path.parent)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("U2NET_HOME", None)
        else:
            os.environ["U2NET_HOME"] = previous


class RembgMattingProvider:
    name = "rembg"

    def remove_background(self, image: Image.Image, *, settings: object | None = None) -> Image.Image:
        model_path = _validate_model_path(settings)
        try:
            from rembg import remove
        except ImportError as exc:
            raise MattingError(
                "rembg is not installed; install the avatar matting extra or choose another provider"
            ) from exc

        input_buffer = BytesIO()
        image.convert("RGBA").save(input_buffer, format="PNG")
        try:
            with _u2net_home_for_model(model_path):
                output = remove(input_buffer.getvalue())
            result = Image.open(BytesIO(output))
            result.load()
        except Exception as exc:  # noqa: BLE001
            raise MattingError(f"rembg failed: {exc}") from exc
        return result.convert("RGBA")
