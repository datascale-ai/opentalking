from __future__ import annotations

from types import SimpleNamespace
import os

from PIL import Image

from opentalking.avatar.matting.rembg_provider import RembgMattingProvider


def test_rembg_provider_requires_configured_model_path(tmp_path, monkeypatch):
    missing_model = tmp_path / "u2net.onnx"
    provider = RembgMattingProvider()

    image = Image.new("RGB", (4, 4), (255, 255, 255))

    try:
        provider.remove_background(image, settings=SimpleNamespace(avatar_matting_model_path=str(missing_model)))
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected missing model to fail before rembg runs")

    assert "未找到抠除背景模型 u2net.onnx" in message
    assert "OPENTALKING_AVATAR_MATTING_MODEL_PATH" in message
    assert "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx" in message
    assert "MD5" not in message
    assert str(missing_model) not in message


def test_rembg_provider_uses_configured_model_directory(tmp_path, monkeypatch):
    model_path = tmp_path / "u2net.onnx"
    model_path.write_bytes(b"fake-model")
    calls: list[bytes] = []
    homes_seen: list[str | None] = []

    def fake_remove(body: bytes) -> bytes:
        calls.append(body)
        homes_seen.append(os.environ.get("U2NET_HOME"))
        out = Image.new("RGBA", (4, 4), (1, 2, 3, 0))
        import io

        buffer = io.BytesIO()
        out.save(buffer, format="PNG")
        return buffer.getvalue()

    monkeypatch.setenv("U2NET_HOME", "/tmp/original-u2net-home")
    monkeypatch.setattr("rembg.remove", fake_remove)

    image = Image.new("RGB", (4, 4), (255, 255, 255))
    result = RembgMattingProvider().remove_background(
        image,
        settings=SimpleNamespace(avatar_matting_model_path=str(model_path)),
    )

    assert calls
    assert homes_seen == [str(tmp_path)]
    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema() == (0, 0)
    assert os.environ.get("U2NET_HOME") == "/tmp/original-u2net-home"
