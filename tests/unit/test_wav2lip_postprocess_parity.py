from __future__ import annotations

from pathlib import Path

from opentalking.avatar.wav2lip_config import (
    DEFAULT_WAV2LIP_POSTPROCESS_MODE,
    optional_wav2lip_postprocess_mode,
)


def test_backend_keeps_easy_enhanced_as_api_only_mode() -> None:
    assert optional_wav2lip_postprocess_mode("easy-enhanced") == "easy_enhanced"


def test_frontend_keeps_easy_enhanced_out_of_regular_options() -> None:
    source = Path("apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")

    assert (
        'export type Wav2LipPostprocessMode = "auto" | "basic" | "opentalking_improved" | '
        '"easy_improved" | "easy_enhanced";'
    ) in source
    options_block = source.split("const WAV2LIP_POSTPROCESS_OPTIONS", 1)[1].split(
        "const FASTERLIVEPORTRAIT_CONTROLS", 1
    )[0]
    assert "easy_enhanced" not in options_block


def test_wav2lip_docs_state_default_and_easy_enhanced_contract() -> None:
    zh_avatar = Path("docs/zh/docs/avatar-format.md").read_text(encoding="utf-8")
    en_avatar = Path("docs/en/docs/avatar-format.md").read_text(encoding="utf-8")
    zh_local = Path("docs/zh/model-deployment/wav2lip/local.md").read_text(encoding="utf-8")
    en_local = Path("docs/en/model-deployment/wav2lip/local.md").read_text(encoding="utf-8")

    assert "默认关闭" not in zh_avatar
    assert "default is disabled" not in en_avatar.lower()
    assert DEFAULT_WAV2LIP_POSTPROCESS_MODE in zh_avatar
    assert DEFAULT_WAV2LIP_POSTPROCESS_MODE in en_avatar
    assert DEFAULT_WAV2LIP_POSTPROCESS_MODE in zh_local
    assert DEFAULT_WAV2LIP_POSTPROCESS_MODE in en_local
    assert "easy_enhanced" in zh_local
    assert "easy_enhanced" in en_local
    assert "GFPGAN" in zh_local
    assert "GFPGAN" in en_local
