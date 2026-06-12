from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuickTalkRootCandidate:
    source: str
    path: Path
    deprecated: bool = False
    default: bool = False


def _path_from_raw(raw: object) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _settings_path(settings: Any | None, name: str) -> Path | None:
    if settings is None:
        return None
    return _path_from_raw(getattr(settings, name, ""))


def _env_path(name: str) -> Path | None:
    return _path_from_raw(os.environ.get(name, ""))


def quicktalk_asset_root_candidates(
    settings: Any | None = None,
    *,
    include_legacy: bool = True,
    include_default: bool = True,
) -> list[QuickTalkRootCandidate]:
    """Return QuickTalk asset-root candidates in the supported priority order.

    New deployments should set only ``OPENTALKING_QUICKTALK_ASSET_ROOT`` or the
    corresponding settings field. The other names are kept only so existing
    installations do not break during upgrades.
    """

    candidates: list[QuickTalkRootCandidate] = []
    settings_asset_root = _settings_path(settings, "quicktalk_asset_root")
    if settings_asset_root is not None:
        candidates.append(
            QuickTalkRootCandidate("settings.quicktalk_asset_root", settings_asset_root)
        )

    env_asset_root = _env_path("OPENTALKING_QUICKTALK_ASSET_ROOT")
    if env_asset_root is not None:
        candidates.append(
            QuickTalkRootCandidate("OPENTALKING_QUICKTALK_ASSET_ROOT", env_asset_root)
        )

    if include_legacy:
        legacy_settings_root = _settings_path(settings, "quicktalk_model_root")
        if legacy_settings_root is not None:
            candidates.append(
                QuickTalkRootCandidate(
                    "settings.quicktalk_model_root",
                    legacy_settings_root,
                    deprecated=True,
                )
            )

        for name in ("OPENTALKING_QUICKTALK_MODEL_ROOT", "OMNIRT_QUICKTALK_MODEL_ROOT"):
            path = _env_path(name)
            if path is not None:
                candidates.append(QuickTalkRootCandidate(name, path, deprecated=True))

        omnirt_model_root = _env_path("OMNIRT_MODEL_ROOT")
        if omnirt_model_root is not None:
            candidates.append(
                QuickTalkRootCandidate(
                    "OMNIRT_MODEL_ROOT/quicktalk",
                    (omnirt_model_root / "quicktalk").resolve(),
                    deprecated=True,
                )
            )

    if include_default and settings is not None:
        models_dir = _path_from_raw(getattr(settings, "models_dir", ""))
        if models_dir is not None:
            candidates.append(
                QuickTalkRootCandidate(
                    "settings.models_dir/quicktalk",
                    (models_dir / "quicktalk").resolve(),
                    default=True,
                )
            )

    return candidates


def resolve_quicktalk_asset_root(
    settings: Any | None = None,
    *,
    include_legacy: bool = True,
    include_default: bool = True,
) -> Path | None:
    candidates = quicktalk_asset_root_candidates(
        settings,
        include_legacy=include_legacy,
        include_default=include_default,
    )
    if not candidates:
        return None
    _warn_conflicting_explicit_roots(candidates)
    return candidates[0].path


def _warn_conflicting_explicit_roots(candidates: list[QuickTalkRootCandidate]) -> None:
    explicit = [candidate for candidate in candidates if not candidate.default]
    unique_paths = {candidate.path for candidate in explicit}
    if len(unique_paths) <= 1:
        return
    formatted = ", ".join(f"{candidate.source}={candidate.path}" for candidate in explicit)
    log.warning(
        "Found conflicting QuickTalk asset roots; using %s=%s. Conflicting roots: %s",
        candidates[0].source,
        candidates[0].path,
        formatted,
    )
