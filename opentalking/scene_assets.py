from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any


SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
SUPPORTED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
SUPPORTED_BACKGROUND_TYPES = SUPPORTED_IMAGE_TYPES | SUPPORTED_VIDEO_TYPES
EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}
VALID_AVATAR_FITS = {"contain", "cover"}
VALID_AVATAR_ANCHORS = {"center", "bottom", "left", "right"}
VALID_SUBTITLE_STYLES = {"none", "compact", "lower-third"}
DEFAULT_BACKGROUNDS = (
    {
        "id": "bg-default-data-wall",
        "name": "数据玻璃幕墙",
        "filename": "default-data-wall.jpg",
        "mime_type": "image/jpeg",
        "resource": "assets/scene_backgrounds/default-data-wall.jpg",
    },
)


def sniff_background_mime(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand in {b"qt  "}:
            return "video/quicktime"
        if brand in {b"mp41", b"mp42", b"isom", b"iso2", b"avc1", b"M4V "}:
            return "video/mp4"
        return "video/mp4"
    if content.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value.strip()).strip("-_")
    return normalized[:48] or fallback


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class SceneAssetStore:
    def __init__(self, root: Path, *, seed_defaults: bool = False) -> None:
        self.root = root.expanduser().resolve()
        self.backgrounds_dir = self.root / "backgrounds"
        self.compositions_dir = self.root / "compositions"
        self.background_index_path = self.backgrounds_dir / "index.json"
        self.composition_index_path = self.compositions_dir / "index.json"
        self.seed_defaults = seed_defaults
        self.background_seed_marker_path = self.backgrounds_dir / ".defaults_seeded"

    def list_backgrounds(self) -> list[dict[str, object]]:
        self._seed_default_backgrounds()
        return self._load_backgrounds()

    def _load_backgrounds(self) -> list[dict[str, object]]:
        items = _read_json(self.background_index_path, [])
        return [item for item in items if isinstance(item, dict)]

    def _seed_default_backgrounds(self) -> None:
        if not self.seed_defaults or self.background_seed_marker_path.exists():
            return
        items = self._load_backgrounds()
        existing_ids = {str(item.get("id") or "") for item in items}
        seeded: list[dict[str, object]] = []
        now = _now()
        for default in DEFAULT_BACKGROUNDS:
            background_id = str(default["id"])
            if background_id in existing_ids:
                continue
            resource_path = resources.files("opentalking").joinpath(str(default["resource"]))
            try:
                content = resource_path.read_bytes()
            except FileNotFoundError:
                continue
            ext = EXT_BY_MIME[str(default["mime_type"])]
            media_path = self.backgrounds_dir / background_id / f"source{ext}"
            media_path.parent.mkdir(parents=True, exist_ok=True)
            media_path.write_bytes(content)
            seeded.append(
                {
                    "id": background_id,
                    "name": str(default["name"]),
                    "kind": "image",
                    "mime_type": str(default["mime_type"]),
                    "filename": str(default["filename"]),
                    "size_bytes": len(content),
                    "url": f"/scene-assets/backgrounds/{background_id}/file",
                    "created_at": now,
                }
            )
        if seeded:
            _write_json(self.background_index_path, [*items, *seeded])
        self.background_seed_marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.background_seed_marker_path.write_text(now + "\n", encoding="utf-8")

    def create_background(self, *, content: bytes, filename: str, mime_type: str, name: str) -> dict[str, object]:
        normalized_mime = (mime_type or "").split(";")[0].strip().lower()
        if not content:
            raise ValueError("empty background asset")
        sniffed_mime = sniff_background_mime(content)
        if sniffed_mime not in SUPPORTED_BACKGROUND_TYPES:
            raise ValueError("unsupported background media type")
        normalized_mime = sniffed_mime
        ext = EXT_BY_MIME[normalized_mime]
        background_id = f"bg-{_slug(name or Path(filename).stem, 'background')}-{uuid.uuid4().hex[:10]}"
        media_path = self.backgrounds_dir / background_id / f"source{ext}"
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(content)
        item: dict[str, object] = {
            "id": background_id,
            "name": (name or Path(filename).stem or background_id).strip(),
            "kind": "video" if normalized_mime.startswith("video/") else "image",
            "mime_type": normalized_mime,
            "filename": filename or f"source{ext}",
            "size_bytes": len(content),
            "url": f"/scene-assets/backgrounds/{background_id}/file",
            "created_at": _now(),
        }
        items = [entry for entry in self._load_backgrounds() if entry.get("id") != background_id]
        items.insert(0, item)
        _write_json(self.background_index_path, items)
        return item

    def background_file_path(self, background_id: str) -> Path | None:
        if not re.fullmatch(r"bg-[\w\u4e00-\u9fff-]+", background_id or ""):
            return None
        item = next((entry for entry in self.list_backgrounds() if entry.get("id") == background_id), None)
        if not item:
            return None
        ext = EXT_BY_MIME.get(str(item.get("mime_type") or ""))
        if not ext:
            return None
        path = (self.backgrounds_dir / background_id / f"source{ext}").resolve()
        try:
            path.relative_to(self.backgrounds_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None

    def delete_background(self, background_id: str) -> bool:
        if not re.fullmatch(r"bg-[\w\u4e00-\u9fff-]+", background_id or ""):
            return False
        items = self._load_backgrounds()
        next_items = [item for item in items if item.get("id") != background_id]
        if len(next_items) == len(items):
            return False
        _write_json(self.background_index_path, next_items)
        shutil.rmtree(self.backgrounds_dir / background_id, ignore_errors=True)
        compositions = [
            {**item, "background_id": None}
            if item.get("background_id") == background_id else item
            for item in self.list_compositions()
        ]
        _write_json(self.composition_index_path, compositions)
        return True

    def list_compositions(self) -> list[dict[str, object]]:
        items = _read_json(self.composition_index_path, [])
        return [item for item in items if isinstance(item, dict)]

    def create_composition(self, payload: dict[str, object]) -> dict[str, object]:
        composition_id = f"scene-{_slug(str(payload.get('name') or 'scene'), 'scene')}-{uuid.uuid4().hex[:10]}"
        now = _now()
        item = self._normalize_composition({**payload, "id": composition_id, "created_at": now, "updated_at": now})
        items = [entry for entry in self.list_compositions() if entry.get("id") != composition_id]
        items.insert(0, item)
        _write_json(self.composition_index_path, items)
        return item

    def update_composition(self, composition_id: str, payload: dict[str, object]) -> dict[str, object] | None:
        items = self.list_compositions()
        for index, item in enumerate(items):
            if item.get("id") != composition_id:
                continue
            updated = self._normalize_composition({**item, **payload, "id": composition_id, "updated_at": _now()})
            items[index] = updated
            _write_json(self.composition_index_path, items)
            return updated
        return None

    def delete_composition(self, composition_id: str) -> bool:
        items = self.list_compositions()
        next_items = [item for item in items if item.get("id") != composition_id]
        if len(next_items) == len(items):
            return False
        _write_json(self.composition_index_path, next_items)
        return True

    def _normalize_composition(self, payload: dict[str, object]) -> dict[str, object]:
        avatar_id = str(payload.get("avatar_id") or "").strip()
        if not avatar_id:
            raise ValueError("avatar_id is required")
        background_id = str(payload.get("background_id") or "").strip() or None
        if background_id and not any(item.get("id") == background_id for item in self.list_backgrounds()):
            raise ValueError("background_id not found")
        avatar_fit = str(payload.get("avatar_fit") or "contain").strip()
        avatar_anchor = str(payload.get("avatar_anchor") or "center").strip()
        subtitle_style = str(payload.get("subtitle_style") or "lower-third").strip()
        raw_avatar_scale = payload.get("avatar_scale")
        if raw_avatar_scale is None:
            avatar_scale = 1.0
        elif isinstance(raw_avatar_scale, str | int | float):
            avatar_scale = float(raw_avatar_scale)
        else:
            raise ValueError("avatar_scale must be a number")
        if avatar_fit not in VALID_AVATAR_FITS:
            raise ValueError("invalid avatar_fit")
        if avatar_anchor not in VALID_AVATAR_ANCHORS:
            raise ValueError("invalid avatar_anchor")
        if subtitle_style not in VALID_SUBTITLE_STYLES:
            raise ValueError("invalid subtitle_style")
        if not 0.5 <= avatar_scale <= 2.0:
            raise ValueError("avatar_scale must be between 0.5 and 2.0")
        return {
            "id": str(payload["id"]),
            "name": str(payload.get("name") or payload["id"]).strip(),
            "avatar_id": avatar_id,
            "background_id": background_id,
            "background_color": str(payload.get("background_color") or "#0f172a").strip(),
            "avatar_fit": avatar_fit,
            "avatar_scale": avatar_scale,
            "avatar_anchor": avatar_anchor,
            "matting_required": bool(payload.get("matting_required", False)),
            "subtitle_style": subtitle_style,
            "created_at": str(payload.get("created_at") or _now()),
            "updated_at": str(payload.get("updated_at") or _now()),
        }
