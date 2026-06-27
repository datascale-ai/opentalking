from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentalking.avatar.manifest import parse_manifest
from opentalking.avatar.validator import assert_valid_avatar_dir
from opentalking.core.interfaces.avatar_asset import AvatarManifest


@dataclass
class AvatarBundle:
    """Resolved avatar on disk + manifest."""

    path: Path
    manifest: AvatarManifest
    extra: dict[str, Any] = field(default_factory=dict)


def load_avatar_bundle(avatar_dir: Path, *, strict: bool = True) -> AvatarBundle:
    avatar_dir = avatar_dir.resolve()
    if strict:
        assert_valid_avatar_dir(avatar_dir)
    manifest = parse_manifest(avatar_dir / "manifest.json")
    return AvatarBundle(path=avatar_dir, manifest=manifest)
