from __future__ import annotations

import pytest

from opentalking.core.model_config import clear_model_config_cache, get_model_backend, get_model_config
from opentalking.core.config import Settings


@pytest.fixture(autouse=True)
def _clear_model_config(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "OPENTALKING_CONFIG_FILE",
        "CONFIG_FILE",
        "OPENTALKING_WAV2LIP_STREAM_BATCH_SIZE",
        "OPENTALKING_WAV2LIP_PADS",
        "OPENTALKING_MUSETALK_CONTEXT_MS",
        "FLASHTALK_FRAME_NUM",
        "OPENTALKING_FLASHTALK_FRAME_NUM",
        "OPENTALKING_WAV2LIP_BACKEND",
        "OPENTALKING_QUICKTALK_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_model_config_cache()
    yield
    clear_model_config_cache()


def test_get_model_config_loads_builtin_defaults(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(tmp_path / "missing.yaml"))
    clear_model_config_cache()

    config = get_model_config("wav2lip")

    assert config["stream_batch_size"] == 8
    assert config["pads"] == [0, 10, 0, 0]


def test_project_config_overrides_builtin_defaults(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  wav2lip:
    stream_batch_size: 12
    pads: [1, 2, 3, 4]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    clear_model_config_cache()

    config = get_model_config("wav2lip")

    assert config["stream_batch_size"] == 12
    assert config["pads"] == [1, 2, 3, 4]


def test_environment_overrides_project_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  wav2lip:
    stream_batch_size: 12
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("OPENTALKING_WAV2LIP_STREAM_BATCH_SIZE", "16")
    clear_model_config_cache()

    assert get_model_config("wav2lip")["stream_batch_size"] == 16


def test_flashtalk_legacy_env_override_still_works(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("FLASHTALK_FRAME_NUM", "44")
    clear_model_config_cache()

    assert get_model_config("flashtalk")["frame_num"] == 44


def test_fasterliveportrait_config_loads_low_latency_defaults(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(tmp_path / "missing.yaml"))
    clear_model_config_cache()

    config = get_model_config("fasterliveportrait")

    assert config["width"] == 448
    assert config["height"] == 900
    assert config["chunk_samples"] == 16000
    assert config["fps"] == 25
    assert config["emit_frames_per_chunk"] == 25
    assert config["render_keyframes_per_chunk"] == 25
    assert config["head_motion_multiplier"] == 0.3
    assert config["pose_motion_multiplier"] == 0.35
    assert config["yaw_multiplier"] == 0.85
    assert config["pitch_multiplier"] == 1.0
    assert config["roll_multiplier"] == 0.85
    assert config["expression_multiplier"] == 1.0
    assert config["driving_multiplier"] == 1.0
    assert config["mouth_open_multiplier"] == 1.25
    assert config["mouth_corner_multiplier"] == 0.85
    assert config["cheek_jaw_multiplier"] == 0.9
    assert config["cfg_scale"] == 4.0
    assert config["animation_region"] == "lip"
    assert config["cfg_cond"] == ["audio"]
    assert config["flag_stitching"] is True
    assert config["flag_relative_motion"] is True
    assert config["flag_normalize_lip"] is True
    assert config["flag_lip_retargeting"] is False
    assert config["disable_frame_interpolation"] is True
    assert config["head_only_pasteback"] is False


def test_settings_exposes_legacy_flashtalk_mode_property() -> None:
    settings = Settings(_env_file=None)

    assert settings.normalized_flashtalk_mode == "flashtalk"


def test_flashtalk_quant_rejects_invalid_enum(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  flashtalk:
    t5_quant: int4
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    clear_model_config_cache()

    with pytest.raises(ValueError, match="t5_quant"):
        get_model_config("flashtalk")


def test_get_model_backend_uses_builtin_compat_defaults(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(tmp_path / "missing.yaml"))
    clear_model_config_cache()

    assert get_model_backend("mock") == "mock"
    assert get_model_backend("quicktalk") == "omnirt"
    assert get_model_backend("flashhead") == "direct_ws"
    assert get_model_backend("fasterliveportrait") == "omnirt"
    assert get_model_backend("wav2lip") == "omnirt"
    assert get_model_backend("musetalk") == "omnirt"


def test_get_model_backend_accepts_project_and_env_overrides(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  wav2lip:
    backend: local
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    clear_model_config_cache()

    assert get_model_backend("wav2lip") == "local"

    monkeypatch.setenv("OPENTALKING_WAV2LIP_BACKEND", "direct_ws")
    clear_model_config_cache()

    assert get_model_backend("wav2lip") == "direct_ws"
