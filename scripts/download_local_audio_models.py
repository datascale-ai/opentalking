from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_ROOT = Path(os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "./models/local-audio"))
DEFAULT_REUSE_ROOTS = (
    Path("./models"),
    Path("/root/models"),
    Path.home() / ".cache" / "opentalking" / "models",
)

MODELS: dict[str, tuple[str, str]] = {
    "sensevoice-small": ("modelscope", "iic/SenseVoiceSmall"),
    "fun-cosyvoice3-0.5b-2512": ("modelscope", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"),
    "indextts2": ("modelscope", "IndexTeam/IndexTTS-2"),
    "indextts2-w2v-bert": ("hf", "facebook/w2v-bert-2.0"),
    "indextts2-maskgct": ("hf", "amphion/MaskGCT"),
    "indextts2-campplus": ("hf", "funasr/campplus"),
    "indextts2-bigvgan": ("hf", "nvidia/bigvgan_v2_22khz_80band_256x"),
}

HF_ALLOW_PATTERNS: dict[str, list[str]] = {
    # IndexTTS2 only needs the feature extractor, model weights, and conformer shim.
    "indextts2-w2v-bert": [
        "README.md",
        "config.json",
        "configuration.json",
        "conformer_shaw.pt",
        "model.safetensors",
        "preprocessor_config.json",
    ],
    # The sidecar maps hf_hub_download("amphion/MaskGCT", "semantic_codec/model.safetensors") here.
    "indextts2-maskgct": [
        "README.md",
        "config.json",
        "semantic_codec/model.safetensors",
        "acoustic_codec/model.safetensors",
        "acoustic_codec/model_1.safetensors",
        "s2a_model/s2a_model_full/model.safetensors",
        "t2s_model/model.safetensors",
    ],
    "indextts2-campplus": [
        "README.md",
        "config.yaml",
        "configuration.json",
        "campplus_cn_common.bin",
        "quickstart.md",
    ],
    # Avoid training and optimizer checkpoints; IndexTTS2 inference loads only the generator and code files.
    "indextts2-bigvgan": [
        "*.py",
        "LICENSE",
        "README.md",
        "config.json",
        "bigvgan_generator.pt",
        "alias_free_activation/**",
    ],
}

MODEL_HINTS: dict[str, tuple[str, ...]] = {
    "sensevoice-small": ("iic__SenseVoiceSmall", "sensevoice", "SenseVoiceSmall"),
    "fun-cosyvoice3-0.5b-2512": (
        "FunAudioLLM__Fun-CosyVoice3-0.5B-2512",
        "Fun-CosyVoice3-0.5B-2512",
        "cosyvoice",
    ),
    "indextts2": ("IndexTeam__IndexTTS-2", "IndexTTS-2"),
    "indextts2-w2v-bert": ("facebook__w2v-bert-2.0", "w2v-bert-2.0"),
    "indextts2-maskgct": ("amphion__MaskGCT", "amphion__MaskGCT-ms"),
    "indextts2-campplus": ("funasr__campplus", "campplus"),
    "indextts2-bigvgan": ("nvidia__bigvgan_v2_22khz_80band_256x", "bigvgan_v2_22khz_80band_256x"),
}

MODEL_REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "sensevoice-small": ("model.pt", "config.yaml", "configuration.json"),
    "fun-cosyvoice3-0.5b-2512": ("cosyvoice3.yaml", "flow.pt", "hift.pt", "llm.pt"),
    "indextts2": ("config.yaml", "model.pt"),
    "indextts2-w2v-bert": ("model.safetensors", "conformer_shaw.pt"),
    "indextts2-maskgct": ("semantic_codec/model.safetensors", "acoustic_codec/model.safetensors"),
    "indextts2-campplus": ("campplus_cn_common.bin", "config.yaml"),
    "indextts2-bigvgan": ("bigvgan_generator.pt",),
}


def default_model_keys() -> list[str]:
    return ["sensevoice-small", "fun-cosyvoice3-0.5b-2512"]


def local_audio_model_ids() -> tuple[str, ...]:
    return tuple(model_id for _, model_id in MODELS.values())


def _target(root: Path, model_id: str) -> Path:
    return root / model_id.replace("/", "__")


def _reuse_root_values(raw: str | None) -> list[Path]:
    if not raw:
        return [root for root in DEFAULT_REUSE_ROOTS if root is not None]
    roots: list[Path] = []
    for chunk in raw.replace(";", os.pathsep).replace(",", os.pathsep).split(os.pathsep):
        value = chunk.strip()
        if value:
            roots.append(Path(value).expanduser())
    return roots


def _model_hints(model_key: str) -> tuple[str, ...]:
    return MODEL_HINTS.get(model_key, (MODELS[model_key][1].replace("/", "__"),))


def _required_files(model_key: str) -> tuple[str, ...]:
    return MODEL_REQUIRED_FILES.get(model_key, ())


def _is_model_ready(path: Path, *, model_key: str) -> bool:
    if not path.exists():
        return False
    required = _required_files(model_key)
    if not required:
        return path.is_dir() or path.is_file()
    return all((path / relative).exists() for relative in required)


def _find_reusable_source(model_key: str, roots: list[Path]) -> Path | None:
    for root in roots:
        for hint in _model_hints(model_key):
            candidate = root / hint
            if _is_model_ready(candidate, model_key=model_key):
                return candidate
            nested = candidate / "checkpoints"
            if _is_model_ready(nested, model_key=model_key):
                return nested
    return None


def _mirror_existing_source(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    try:
        target.symlink_to(source, target_is_directory=source.is_dir())
        return
    except Exception:
        pass
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _download_modelscope(model_id: str, target: Path) -> None:
    from modelscope import snapshot_download

    cached = Path(snapshot_download(model_id, local_dir=str(target)))
    if cached != target and cached.exists() and not target.exists():
        shutil.copytree(cached, target)


def _download_hf(model_id: str, target: Path, *, model_key: str) -> None:
    from huggingface_hub import snapshot_download

    endpoint = os.environ.get("HF_ENDPOINT", "").strip()
    kwargs = {"repo_id": model_id, "local_dir": str(target)}
    if endpoint:
        kwargs["endpoint"] = endpoint
    if patterns := HF_ALLOW_PATTERNS.get(model_key):
        kwargs["allow_patterns"] = patterns
    snapshot_download(**kwargs)


def _git_lfs_pull_if_needed(target: Path) -> None:
    if (target / ".git").exists() and shutil.which("git"):
        subprocess.run(["git", "-C", str(target), "lfs", "pull"], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the supported local STT/TTS model weights.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--reuse-root",
        action="append",
        dest="reuse_roots",
        help="Search these roots first and reuse existing weights instead of downloading.",
    )
    parser.add_argument(
        "--model",
        action="append",
        choices=sorted(MODELS),
        help="Model key to download. Defaults to SenseVoiceSmall and CosyVoice3-0.5B-2512.",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = args.model or default_model_keys()
    reuse_roots = [root] + _reuse_root_values(os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_SEARCH_ROOTS"))
    if args.reuse_roots:
        reuse_roots.extend(Path(value).expanduser().resolve() for value in args.reuse_roots)

    failures: list[tuple[str, str]] = []
    for key in selected:
        source, model_id = MODELS[key]
        target = _target(root, model_id)
        print(f"[{key}] {source}:{model_id} -> {target}", flush=True)
        target.mkdir(parents=True, exist_ok=True)
        try:
            if _is_model_ready(target, model_key=key):
                print(f"[{key}] reusing existing target: {target}", flush=True)
                continue

            reusable = _find_reusable_source(key, reuse_roots)
            if reusable is not None:
                print(f"[{key}] reusing existing source: {reusable}", flush=True)
                if reusable.resolve() != target.resolve():
                    _mirror_existing_source(reusable, target)
                continue

            if source == "modelscope":
                _download_modelscope(model_id, target)
            else:
                _download_hf(model_id, target, model_key=key)
            _git_lfs_pull_if_needed(target)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            failures.append((key, message))
            print(f"[{key}] failed: {message}", file=sys.stderr, flush=True)
            continue

    if failures:
        print("\nFailed downloads:", file=sys.stderr)
        for key, message in failures:
            print(f"- {key}: {message}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
