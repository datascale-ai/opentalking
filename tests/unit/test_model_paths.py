from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_model_root_priority(monkeypatch, tmp_path):
    from opentalking.core.model_paths import model_root

    configured = tmp_path / "configured-models"
    digital_home = tmp_path / "digital-human"
    env_root = tmp_path / "env-models"

    monkeypatch.delenv("OPENTALKING_MODEL_ROOT", raising=False)
    monkeypatch.delenv("DIGITAL_HUMAN_HOME", raising=False)

    assert model_root(configured) == configured

    monkeypatch.setenv("DIGITAL_HUMAN_HOME", str(digital_home))
    assert model_root() == digital_home / "models"
    assert model_root(configured) == configured

    monkeypatch.setenv("OPENTALKING_MODEL_ROOT", str(env_root))
    assert model_root() == env_root
    assert model_root(configured) == env_root


def test_model_subroots_use_unified_model_root(monkeypatch, tmp_path):
    from opentalking.core.model_paths import (
        local_audio_model_root,
        quicktalk_asset_root,
        wav2lip_model_root,
    )

    model_root = tmp_path / "models"
    monkeypatch.setenv("OPENTALKING_MODEL_ROOT", str(model_root))
    monkeypatch.delenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", raising=False)
    monkeypatch.delenv("OPENTALKING_QUICKTALK_ASSET_ROOT", raising=False)
    monkeypatch.delenv("OPENTALKING_WAV2LIP_MODEL_ROOT", raising=False)

    assert local_audio_model_root() == model_root / "local-audio"
    assert quicktalk_asset_root() == model_root / "quicktalk"
    assert wav2lip_model_root() == model_root / "wav2lip"

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "audio"))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(tmp_path / "quicktalk"))
    monkeypatch.setenv("OPENTALKING_WAV2LIP_MODEL_ROOT", str(tmp_path / "wav2lip"))

    assert local_audio_model_root() == tmp_path / "audio"
    assert quicktalk_asset_root() == tmp_path / "quicktalk"
    assert wav2lip_model_root() == tmp_path / "wav2lip"


def test_model_repo_and_runtime_roots_default_to_digital_home(monkeypatch, tmp_path):
    from opentalking.core.model_paths import model_repo_root, runtime_root

    digital_home = tmp_path / "digital-human"
    monkeypatch.setenv("DIGITAL_HUMAN_HOME", str(digital_home))
    monkeypatch.delenv("OPENTALKING_MODEL_REPO_ROOT", raising=False)
    monkeypatch.delenv("OPENTALKING_RUNTIME_ROOT", raising=False)

    assert model_repo_root() == digital_home / "model-repos"
    assert runtime_root() == digital_home / "runtimes"

    monkeypatch.setenv("OPENTALKING_MODEL_REPO_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("OPENTALKING_RUNTIME_ROOT", str(tmp_path / "runtime-envs"))

    assert model_repo_root() == tmp_path / "repos"
    assert runtime_root() == tmp_path / "runtime-envs"


def test_musetalk_v15_layout_resolves_under_model_root(tmp_path):
    from opentalking.models.musetalk.loader import resolve_musetalk_v15

    model_root = tmp_path / "models"
    (model_root / "musetalk").mkdir(parents=True)
    (model_root / "musetalk" / "pytorch_model.bin").write_bytes(b"weights")
    (model_root / "musetalk" / "musetalk.json").write_text("{}", encoding="utf-8")
    (model_root / "sd-vae-ft-mse").mkdir()
    (model_root / "whisper").mkdir()
    (model_root / "whisper" / "tiny.pt").write_bytes(b"whisper")
    (model_root / "dwpose").mkdir()
    (model_root / "dwpose" / "dw-ll_ucoco_384.pth").write_bytes(b"dwpose")
    (model_root / "face-parse-bisenet").mkdir()
    (model_root / "face-parse-bisenet" / "79999_iter.pth").write_bytes(b"face")

    resolved = resolve_musetalk_v15(model_root)

    assert resolved is not None
    assert resolved["unet_weights"] == model_root / "musetalk" / "pytorch_model.bin"
    assert resolved["unet_config"] == model_root / "musetalk" / "musetalk.json"
    assert resolved["vae_dir"] == model_root / "sd-vae-ft-mse"
    assert resolved["whisper"] == model_root / "whisper" / "tiny.pt"
    assert resolved["dwpose"] == model_root / "dwpose" / "dw-ll_ucoco_384.pth"
    assert resolved["face_parse"] == model_root / "face-parse-bisenet" / "79999_iter.pth"


def test_voice_assets_loads_without_core_config_dependencies():
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import importlib.util
from pathlib import Path
import sys

class BlockPydanticSettings(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pydantic_settings":
            raise ImportError("blocked for standalone sidecar test")
        return None

sys.meta_path.insert(0, BlockPydanticSettings())
module_path = Path("opentalking/providers/tts/voice_assets.py").resolve()
spec = importlib.util.spec_from_file_location("_voice_assets_sidecar_test", module_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert module.local_audio_model_root().name == "local-audio"
"""

    subprocess.run([sys.executable, "-c", script], cwd=repo_root, check=True)
