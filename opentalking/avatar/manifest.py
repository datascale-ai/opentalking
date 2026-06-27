from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opentalking.core.interfaces.avatar_asset import AvatarManifest


def parse_manifest(path: Path) -> AvatarManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return manifest_from_dict(raw)


def manifest_from_dict(raw: dict[str, Any]) -> AvatarManifest:
    required = ["id", "model_type", "fps", "sample_rate", "width", "height", "version"]
    for k in required:
        if k not in raw:
            raise ValueError(f"manifest missing field: {k}")
    return AvatarManifest(
        id=str(raw["id"]),
        model_type=str(raw["model_type"]),
        fps=int(raw["fps"]),
        sample_rate=int(raw["sample_rate"]),
        width=int(raw["width"]),
        height=int(raw["height"]),
        version=str(raw["version"]),
        name=raw.get("name"),
        metadata=dict(raw.get("metadata") or {}),
    )
