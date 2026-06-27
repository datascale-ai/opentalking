from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


INDEXTTS_PROVIDER = "indextts"
INDEXTTS_LEGACY_PROVIDERS = {"local_indextts", "omnirt_indextts"}
INDEXTTS_PROVIDERS = {INDEXTTS_PROVIDER, *INDEXTTS_LEGACY_PROVIDERS}
LOCAL_COSYVOICE_PROVIDER = "local_cosyvoice"


@dataclass(frozen=True)
class VoiceAsset:
    voice_id: str
    source: str
    root: Path
    path: Path
    prompt_audio: Path
    prompt_text: Path | None
    meta: dict[str, Any]
    bundled_system: bool = False


def local_audio_model_root() -> Path:
    raw = os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "").strip()
    try:
        from opentalking.core.config import get_settings

        raw = raw or (get_settings().local_audio_model_root or "").strip()
    except Exception:
        pass
    return Path(raw or "./models/local-audio").expanduser().resolve()


def bundled_system_voice_root() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "voices" / "system"


def system_voice_roots(model_root: Path | None = None) -> list[Path]:
    root = model_root or local_audio_model_root()
    roots = [root / "voices" / "system", bundled_system_voice_root()]
    out: list[Path] = []
    seen: set[Path] = set()
    for item in roots:
        try:
            resolved = item.resolve()
        except OSError:
            resolved = item
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(item)
    return out


def clone_voice_roots(model_root: Path | None = None) -> list[Path]:
    root = model_root or local_audio_model_root()
    return [root / "voices" / "clones"]


def _provider_aliases(provider: str) -> set[str]:
    normalized = provider.strip().lower()
    if normalized in INDEXTTS_PROVIDERS:
        return {INDEXTTS_PROVIDER, *INDEXTTS_LEGACY_PROVIDERS}
    return {normalized}


def _truthy_meta_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "universal", "zero_shot"}
    return False


def voice_applies_to_provider(meta: dict[str, Any], provider: str, *, bundled_system: bool = False) -> bool:
    normalized = provider.strip().lower()
    if not normalized:
        return True
    if bundled_system and normalized == LOCAL_COSYVOICE_PROVIDER:
        return True
    if any(_truthy_meta_flag(meta.get(key)) for key in ("universal", "compatible", "zero_shot_compatible")):
        return True
    aliases = _provider_aliases(normalized)
    raw_providers = meta.get("providers")
    if isinstance(raw_providers, list):
        allowed = {str(item).strip().lower() for item in raw_providers if str(item).strip()}
        if allowed:
            return bool(allowed & aliases)
    raw_provider = str(meta.get("provider") or "").strip().lower()
    if not raw_provider:
        return True
    if normalized == LOCAL_COSYVOICE_PROVIDER and raw_provider in INDEXTTS_PROVIDERS and not raw_providers:
        return True
    return raw_provider in aliases


def read_voice_meta(voice_dir: Path) -> dict[str, Any]:
    meta_path = voice_dir / "meta.json"
    if not meta_path.is_file():
        return {}
    try:
        parsed = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def iter_voice_assets(
    *,
    provider: str,
    sources: Iterable[str] = ("clones", "system"),
    model_root: Path | None = None,
    require_prompt_text: bool = False,
) -> list[VoiceAsset]:
    root = model_root or local_audio_model_root()
    roots: list[tuple[str, Path, bool]] = []
    for source in sources:
        if source == "clones":
            roots.extend(("clones", item, False) for item in clone_voice_roots(root))
        elif source == "system":
            bundled = bundled_system_voice_root()
            for item in system_voice_roots(root):
                roots.append(("system", item, _same_path(item, bundled)))

    assets: list[VoiceAsset] = []
    seen: set[tuple[str, str]] = set()
    for source, voice_root, bundled_system in roots:
        if not voice_root.is_dir():
            continue
        for voice_dir in sorted(path for path in voice_root.iterdir() if path.is_dir()):
            voice_id = voice_dir.name
            key = (source, voice_id)
            if key in seen:
                continue
            prompt_audio = voice_dir / "prompt.wav"
            prompt_text = voice_dir / "prompt.txt"
            if not prompt_audio.is_file():
                continue
            if require_prompt_text and not prompt_text.is_file():
                continue
            meta = read_voice_meta(voice_dir)
            if not voice_applies_to_provider(meta, provider, bundled_system=bundled_system):
                continue
            seen.add(key)
            assets.append(
                VoiceAsset(
                    voice_id=voice_id,
                    source=source,
                    root=voice_root,
                    path=voice_dir,
                    prompt_audio=prompt_audio,
                    prompt_text=prompt_text if prompt_text.is_file() else None,
                    meta=meta,
                    bundled_system=bundled_system,
                )
            )
    return assets


def resolve_voice_asset(
    voice_id: str,
    *,
    provider: str,
    sources: Iterable[str] = ("clones", "system"),
    model_root: Path | None = None,
    require_prompt_text: bool = False,
) -> VoiceAsset | None:
    wanted = voice_id.strip()
    if not wanted:
        return None
    for asset in iter_voice_assets(
        provider=provider,
        sources=sources,
        model_root=model_root,
        require_prompt_text=require_prompt_text,
    ):
        if asset.voice_id == wanted:
            return asset
    return None


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right
