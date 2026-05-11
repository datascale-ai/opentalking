from __future__ import annotations

from pathlib import Path

import pytest

from opentalking.models.quicktalk.adapter import QuickTalkAdapter


def test_quicktalk_adapter_treats_empty_asset_root_env_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", "")
    adapter = QuickTalkAdapter()
    assert adapter._asset_root is None


def test_quicktalk_adapter_prefers_env_asset_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "hdModule"
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(asset_root))
    adapter = QuickTalkAdapter()
    assert adapter._asset_root == asset_root.resolve()
