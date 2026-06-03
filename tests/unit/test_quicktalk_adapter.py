from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from opentalking.core.types.frames import VideoFrameData
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


def test_quicktalk_runtime_available_rejects_unavailable_explicit_cuda(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_pth_assets(asset_root)

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    fake_torch = types.SimpleNamespace(cuda=FakeCuda())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_ROOT", str(asset_root))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_DEVICE", "cuda:6")

    assert QuickTalkAdapter.runtime_available() is False


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


def test_quicktalk_adapter_falls_back_to_model_root_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_pth_assets(asset_root)
    avatar_dir = tmp_path / "avatars" / "anchor"
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir(parents=True)
    template = quicktalk_dir / "template_512x512.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 512,
                "height": 512,
                "version": "1.0",
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
    monkeypatch.delenv("OPENTALKING_QUICKTALK_ASSET_ROOT", raising=False)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_ROOT", str(asset_root))

    adapter = QuickTalkAdapter()
    adapter.load_avatar(str(avatar_dir))

    assert captured["asset_root"] == asset_root.resolve()
    assert captured["template_video"] == template.resolve()


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


def test_quicktalk_adapter_prefers_prepared_avatar_template_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_local_assets(asset_root)
    avatar_dir = tmp_path / "avatars" / "singer"
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir(parents=True)
    prepared_template = quicktalk_dir / "template_674x900.mp4"
    prepared_cache = quicktalk_dir / "face_cache_v3_674x900.npz"
    source_video = avatar_dir / "source" / "source.mp4"
    source_video.parent.mkdir()
    prepared_template.write_bytes(b"prepared-video")
    prepared_cache.write_bytes(b"prepared-cache")
    source_video.write_bytes(b"source-video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "singer",
                "model_type": "wav2lip",
                "fps": 30,
                "sample_rate": 16000,
                "width": 830,
                "height": 1108,
                "version": "1.0",
                "metadata": {"source_video": "source/source.mp4"},
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, Path | None] = {}

    class FakeWorker:
        fps = 25

        def __init__(
            self,
            *,
            asset_root: Path,
            template_video: Path,
            face_cache_dir: Path | None,
            face_cache_file: Path | None,
            **_: object,
        ) -> None:
            captured["asset_root"] = asset_root
            captured["template_video"] = template_video
            captured["face_cache_dir"] = face_cache_dir
            captured["face_cache_file"] = face_cache_file

        def make_state(self) -> object:
            return object()

    fake_runtime = types.ModuleType("opentalking.models.quicktalk.runtime")
    fake_runtime.RealtimeV3Worker = FakeWorker
    monkeypatch.setitem(sys.modules, "opentalking.models.quicktalk.runtime", fake_runtime)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(asset_root))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MAX_LONG_EDGE", "900")

    adapter = QuickTalkAdapter()
    adapter.load_avatar(str(avatar_dir))

    assert captured["asset_root"] == asset_root.resolve()
    assert captured["template_video"] == prepared_template.resolve()
    assert captured["face_cache_file"] == prepared_cache.resolve()
    assert captured["face_cache_dir"] == asset_root.resolve() / ".face_cache_v3"


def test_quicktalk_adapter_uses_bundled_quicktalk_template_when_metadata_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_pth_assets(asset_root)
    avatar_dir = tmp_path / "avatars" / "office-woman"
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir(parents=True)
    template = quicktalk_dir / "template_900.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "office-woman",
                "model_type": "wav2lip",
                "fps": 30,
                "sample_rate": 16000,
                "width": 540,
                "height": 900,
                "version": "1.0",
                "metadata": {},
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


def test_quicktalk_adapter_uses_prepared_image_avatar_template_without_video_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_local_assets(asset_root)
    avatar_dir = tmp_path / "avatars" / "ancient-beauty"
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir(parents=True)
    prepared_template = quicktalk_dir / "template_720x900.mp4"
    prepared_cache = quicktalk_dir / "face_cache_v3_720x900.npz"
    prepared_template.write_bytes(b"prepared-video")
    prepared_cache.write_bytes(b"prepared-cache")
    (avatar_dir / "reference.png").write_bytes(b"png")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "ancient-beauty",
                "model_type": "wav2lip",
                "fps": 30,
                "sample_rate": 16000,
                "width": 720,
                "height": 900,
                "version": "1.0",
                "metadata": {
                    "reference_mode": "image",
                    "source_image": "reference.png",
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, Path | None] = {}

    class FakeWorker:
        fps = 25

        def __init__(
            self,
            *,
            template_video: Path,
            face_cache_file: Path | None,
            **_: object,
        ) -> None:
            captured["template_video"] = template_video
            captured["face_cache_file"] = face_cache_file

        def make_state(self) -> object:
            return object()

    fake_runtime = types.ModuleType("opentalking.models.quicktalk.runtime")
    fake_runtime.RealtimeV3Worker = FakeWorker
    monkeypatch.setitem(sys.modules, "opentalking.models.quicktalk.runtime", fake_runtime)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(asset_root))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MAX_LONG_EDGE", "900")

    adapter = QuickTalkAdapter()
    adapter.load_avatar(str(avatar_dir))

    assert captured["template_video"] == prepared_template.resolve()
    assert captured["face_cache_file"] == prepared_cache.resolve()


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


def test_quicktalk_adapter_warmup_runs_silence_and_restores_stream_state() -> None:
    adapter = QuickTalkAdapter()
    calls: list[tuple[np.ndarray, int]] = []

    class FakeWorker:
        fps = 25

        def make_state(self):
            return {"fresh": True}

        def prepare_pcm_features(self, pcm, sample_rate):
            calls.append((pcm.copy(), sample_rate))
            return [np.zeros((10, 1024), dtype=np.float32)], 0.01

        def generate_frames_from_reps(self, reps, state=None):
            assert state == {"fresh": True}
            for _ in reps:
                yield np.zeros((4, 4, 3), dtype=np.uint8)

    state = types.SimpleNamespace(
        worker=FakeWorker(),
        fps=25,
        frame_index=7,
        session_state={"existing": True},
    )

    def fake_compose_frame(avatar_state, frame_idx, prediction):
        assert avatar_state is state
        assert frame_idx == 7
        assert isinstance(prediction, np.ndarray)
        return VideoFrameData(data=np.zeros((4, 4, 3), dtype=np.uint8), width=4, height=4, timestamp_ms=0.0)

    adapter.compose_frame = fake_compose_frame  # type: ignore[method-assign]

    adapter.warmup(state)  # type: ignore[arg-type]

    assert len(calls) == 1
    pcm, sample_rate = calls[0]
    assert sample_rate == 16000
    assert pcm.dtype == np.int16
    assert pcm.shape[0] >= 3200
    assert np.all(pcm == 0)
    assert state.frame_index == 7
    assert state.session_state == {"existing": True}


def test_quicktalk_adapter_evicts_old_worker_cache_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking.models.quicktalk import adapter as quicktalk_adapter

    quicktalk_adapter._WORKER_CACHE.clear()
    monkeypatch.setenv("OPENTALKING_QUICKTALK_WORKER_CACHE_MAX", "1")
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_pth_assets(asset_root)
    closed: list[str] = []

    class FakeWorker:
        fps = 25

        def __init__(self, *, template_video: Path, **_: object) -> None:
            self.template_video = template_video

        def make_state(self) -> object:
            return object()

        def close(self) -> None:
            closed.append(self.template_video.name)

    fake_runtime = types.ModuleType("opentalking.models.quicktalk.runtime")
    fake_runtime.RealtimeV3Worker = FakeWorker
    monkeypatch.setitem(sys.modules, "opentalking.models.quicktalk.runtime", fake_runtime)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(asset_root))

    for avatar_id in ("first", "second"):
        avatar_dir = tmp_path / "avatars" / avatar_id
        quicktalk_dir = avatar_dir / "quicktalk"
        quicktalk_dir.mkdir(parents=True)
        (quicktalk_dir / "template_512x512.mp4").write_bytes(avatar_id.encode())
        (avatar_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": avatar_id,
                    "model_type": "quicktalk",
                    "fps": 25,
                    "sample_rate": 16000,
                    "width": 512,
                    "height": 512,
                    "version": "1.0",
                }
            ),
            encoding="utf-8",
        )

    adapter = QuickTalkAdapter()
    adapter.load_avatar(str(tmp_path / "avatars" / "first"))
    adapter.load_avatar(str(tmp_path / "avatars" / "second"))

    assert closed == ["template_512x512.mp4"]
    assert len(quicktalk_adapter._WORKER_CACHE) == 1
    quicktalk_adapter._WORKER_CACHE.clear()
