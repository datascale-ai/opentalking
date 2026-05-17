from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from opentalking.models.quicktalk.adapter import QuickTalkAdapter


def _write_quicktalk_local_assets(asset_root: Path) -> None:
    checkpoints = asset_root / "checkpoints"
    (checkpoints / "chinese-hubert-large").mkdir(parents=True)
    (checkpoints / "auxiliary" / "models" / "buffalo_l").mkdir(parents=True)
    (checkpoints / "256.onnx").write_bytes(b"onnx")
    (checkpoints / "repair.npy").write_bytes(b"npy")
    (checkpoints / "chinese-hubert-large" / "pytorch_model.bin").write_bytes(b"hubert")
    (checkpoints / "auxiliary" / "models" / "buffalo_l" / "det_10g.onnx").write_bytes(
        b"det"
    )


def _write_quicktalk_pth_assets(asset_root: Path) -> None:
    checkpoints = asset_root / "checkpoints"
    (checkpoints / "chinese-hubert-large").mkdir(parents=True)
    (checkpoints / "auxiliary" / "models" / "buffalo_l").mkdir(parents=True)
    (checkpoints / "quicktalk.pth").write_bytes(b"pth")
    (checkpoints / "repair.npy").write_bytes(b"npy")
    (checkpoints / "chinese-hubert-large" / "pytorch_model.bin").write_bytes(b"hubert")
    (checkpoints / "auxiliary" / "models" / "buffalo_l" / "det_10g.onnx").write_bytes(
        b"det"
    )


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


def test_quicktalk_adapter_accepts_avatar_with_quicktalk_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_local_assets(asset_root)
    avatar_dir = tmp_path / "avatars" / "anchor"
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir(parents=True)
    template = quicktalk_dir / "template_900.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "model_type": "flashhead",
                "fps": 25,
                "sample_rate": 16000,
                "width": 512,
                "height": 512,
                "version": "1.0",
                "metadata": {
                    "quicktalk": {
                        "template_video": "quicktalk/template_900.mp4",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, Path] = {}

    class FakeWorker:
        fps = 25

        def __init__(self, *, asset_root: Path, template_video: Path, **_: object) -> None:
            captured["asset_root"] = asset_root
            captured["template_video"] = template_video

        def make_state(self) -> object:
            return object()

    fake_runtime = types.ModuleType("opentalking.models.quicktalk.runtime")
    fake_runtime.RealtimeV3Worker = FakeWorker
    monkeypatch.setitem(sys.modules, "opentalking.models.quicktalk.runtime", fake_runtime)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(asset_root))

    adapter = QuickTalkAdapter()
    state = adapter.load_avatar(str(avatar_dir))

    assert state.manifest.model_type == "flashhead"
    assert captured["asset_root"] == asset_root.resolve()
    assert captured["template_video"] == template.resolve()


def test_quicktalk_adapter_normalizes_hdmodule_asset_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_parent = tmp_path / "models" / "quicktalk"
    hd_module = asset_parent / "hdModule"
    _write_quicktalk_local_assets(hd_module)
    avatar_dir = tmp_path / "avatars" / "anchor"
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir(parents=True)
    template = quicktalk_dir / "template_900.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "model_type": "flashhead",
                "fps": 25,
                "sample_rate": 16000,
                "width": 512,
                "height": 512,
                "version": "1.0",
                "metadata": {
                    "quicktalk": {
                        "asset_root": str(asset_parent),
                        "template_video": "quicktalk/template_900.mp4",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, Path] = {}

    class FakeWorker:
        fps = 25

        def __init__(self, *, asset_root: Path, template_video: Path, **_: object) -> None:
            captured["asset_root"] = asset_root
            captured["template_video"] = template_video

        def make_state(self) -> object:
            return object()

    fake_runtime = types.ModuleType("opentalking.models.quicktalk.runtime")
    fake_runtime.RealtimeV3Worker = FakeWorker
    monkeypatch.setitem(sys.modules, "opentalking.models.quicktalk.runtime", fake_runtime)

    adapter = QuickTalkAdapter()
    adapter.load_avatar(str(avatar_dir))

    assert captured["asset_root"] == hd_module.resolve()
    assert captured["template_video"] == template.resolve()


def test_quicktalk_adapter_accepts_pth_model_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_pth_assets(asset_root)
    avatar_dir = tmp_path / "avatars" / "anchor"
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir(parents=True)
    template = quicktalk_dir / "template_900.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "model_type": "flashhead",
                "fps": 25,
                "sample_rate": 16000,
                "width": 512,
                "height": 512,
                "version": "1.0",
                "metadata": {
                    "quicktalk": {
                        "template_video": "quicktalk/template_900.mp4",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, Path] = {}

    class FakeWorker:
        fps = 25

        def __init__(self, *, asset_root: Path, template_video: Path, **_: object) -> None:
            captured["asset_root"] = asset_root
            captured["template_video"] = template_video

        def make_state(self) -> object:
            return object()

    fake_runtime = types.ModuleType("opentalking.models.quicktalk.runtime")
    fake_runtime.RealtimeV3Worker = FakeWorker
    monkeypatch.setitem(sys.modules, "opentalking.models.quicktalk.runtime", fake_runtime)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(asset_root))

    adapter = QuickTalkAdapter()
    state = adapter.load_avatar(str(avatar_dir))

    assert state.manifest.model_type == "flashhead"
    assert captured["asset_root"] == asset_root.resolve()
    assert captured["template_video"] == template.resolve()


def test_quicktalk_adapter_reports_flat_asset_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    asset_root.mkdir(parents=True)
    (asset_root / "quicktalk.pth").write_bytes(b"pth")
    (asset_root / "repair.npy").write_bytes(b"npy")
    avatar_dir = tmp_path / "avatars" / "anchor"
    avatar_dir.mkdir(parents=True)
    template = avatar_dir / "template.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "model_type": "flashhead",
                "fps": 25,
                "sample_rate": 16000,
                "width": 512,
                "height": 512,
                "version": "1.0",
                "metadata": {"quicktalk": {"template_video": "template.mp4"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(asset_root))

    adapter = QuickTalkAdapter()
    with pytest.raises(FileNotFoundError, match="quicktalk\\.pth or 256\\.onnx"):
        adapter.load_avatar(str(avatar_dir))
