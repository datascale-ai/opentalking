from __future__ import annotations

import pytest

import apps.api.main as api_main
import apps.unified.main as unified_main
from opentalking.core.config import Settings


@pytest.mark.parametrize(
    ("cors_origins", "expected"),
    [
        ("*", ["*"]),
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        (["http://a.test", "http://b.test"], ["http://a.test", "http://b.test"]),
    ],
)
def test_create_app_accepts_supported_cors_formats(
    monkeypatch: pytest.MonkeyPatch,
    cors_origins: str | list[str],
    expected: list[str],
) -> None:
    settings = Settings(cors_origins=cors_origins)
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)
    monkeypatch.setattr(unified_main, "get_settings", lambda: settings)

    api_app = api_main.create_app()
    unified_app = unified_main.create_app()

    assert api_app.user_middleware[0].kwargs["allow_origins"] == expected
    assert unified_app.user_middleware[0].kwargs["allow_origins"] == expected


def test_wav2lip_preload_defaults_on() -> None:
    settings = Settings()

    assert settings.wav2lip_preload is True


def test_unprefixed_omnirt_endpoint_is_read_from_dotenv(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_OMNIRT_ENDPOINT", raising=False)
    (tmp_path / ".env").write_text(
        "OMNIRT_ENDPOINT=http://127.0.0.1:9000\n"
        "OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE=/v1/audio2video/{model}\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.omnirt_endpoint == "http://127.0.0.1:9000"
    assert settings.omnirt_audio2video_path_template == "/v1/audio2video/{model}"


def test_prefixed_omnirt_endpoint_takes_precedence_over_unprefixed_dotenv(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENTALKING_OMNIRT_ENDPOINT", "http://10.0.0.2:9000")
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    (tmp_path / ".env").write_text(
        "OMNIRT_ENDPOINT=http://127.0.0.1:9000\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.omnirt_endpoint == "http://10.0.0.2:9000"



def test_export_settings_defaults_and_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("OPENTALKING_EXPORTS_DIR", "/tmp/opentalking-exports")
    monkeypatch.setenv("OPENTALKING_EXPORT_MAX_BYTES", "2048")

    settings = Settings(_env_file=None)

    assert settings.exports_dir == "/tmp/opentalking-exports"
    assert settings.export_max_bytes == 2048


def test_export_settings_have_safe_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENTALKING_EXPORTS_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_EXPORT_MAX_BYTES", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert settings.exports_dir == "./data/exports"
    assert settings.export_max_bytes == 1024 * 1024 * 1024
