from __future__ import annotations

import pytest

from opentalking.core.model_config import clear_model_config_cache, get_model_config
from opentalking.models.musetalk.adapter import MuseTalkAdapter
from opentalking.models.wav2lip.adapter import Wav2LipAdapter


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


def test_wav2lip_pads_accept_yaml_list_and_env_string(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  wav2lip:
    pads: [1, 2, 3, 4]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    clear_model_config_cache()
    assert Wav2LipAdapter()._pads == (1, 2, 3, 4)

    monkeypatch.setenv("OPENTALKING_WAV2LIP_PADS", "5,6,7,8")
    clear_model_config_cache()
    assert Wav2LipAdapter()._pads == (5, 6, 7, 8)


def test_musetalk_adapter_uses_model_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  musetalk:
    context_ms: 480.0
    silence_gate: 0.08
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    clear_model_config_cache()

    adapter = MuseTalkAdapter()

    assert adapter._stream_context_ms == 480.0
    assert adapter._silence_gate_threshold == 0.08
