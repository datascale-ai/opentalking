from __future__ import annotations

import os
from pathlib import Path


def _path_from_raw(raw: str | os.PathLike[str] | None) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def digital_human_home(*, repo_root: str | os.PathLike[str] | None = None) -> Path | None:
    raw = _path_from_raw(os.environ.get("DIGITAL_HUMAN_HOME"))
    if raw is not None:
        return raw
    if repo_root is not None:
        return Path(repo_root).expanduser().resolve().parent
    return None


def model_root(configured: str | os.PathLike[str] | None = None) -> Path:
    env_root = _path_from_raw(os.environ.get("OPENTALKING_MODEL_ROOT"))
    if env_root is not None:
        return env_root
    configured_root = _path_from_raw(configured)
    if configured_root is not None:
        return configured_root
    home = digital_human_home()
    if home is not None:
        return home / "models"
    return Path("./models")


def model_subdir(
    name: str,
    *,
    explicit_env: str = "",
    configured: str | os.PathLike[str] | None = None,
) -> Path:
    if explicit_env:
        env_root = _path_from_raw(os.environ.get(explicit_env))
        if env_root is not None:
            return env_root
    configured_root = _path_from_raw(configured)
    if configured_root is not None:
        return configured_root
    return model_root() / name


def local_audio_model_root(configured: str | os.PathLike[str] | None = None) -> Path:
    return model_subdir(
        "local-audio",
        explicit_env="OPENTALKING_LOCAL_AUDIO_MODEL_ROOT",
        configured=configured,
    )


def quicktalk_asset_root(configured: str | os.PathLike[str] | None = None) -> Path:
    return model_subdir(
        "quicktalk",
        explicit_env="OPENTALKING_QUICKTALK_ASSET_ROOT",
        configured=configured,
    )


def wav2lip_model_root(configured: str | os.PathLike[str] | None = None) -> Path:
    return model_subdir(
        "wav2lip",
        explicit_env="OPENTALKING_WAV2LIP_MODEL_ROOT",
        configured=configured,
    )


def model_repo_root(*, repo_root: str | os.PathLike[str] | None = None) -> Path:
    env_root = _path_from_raw(os.environ.get("OPENTALKING_MODEL_REPO_ROOT"))
    if env_root is not None:
        return env_root
    home = digital_human_home(repo_root=repo_root)
    if home is not None:
        return home / "model-repos"
    return Path("./model-repos")


def runtime_root(*, repo_root: str | os.PathLike[str] | None = None) -> Path:
    env_root = _path_from_raw(os.environ.get("OPENTALKING_RUNTIME_ROOT"))
    if env_root is not None:
        return env_root
    home = digital_human_home(repo_root=repo_root)
    if home is not None:
        return home / "runtimes"
    return Path("./runtimes")
