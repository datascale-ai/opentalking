from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ALLOWED_KINDS = {"realtime_dialogue", "video_clone", "video_creation"}
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")
_MIME_EXTENSIONS = {
    "video/webm": ".webm",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/x-matroska": ".mkv",
}


class ExportTooLargeError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _root(root: Path | str) -> Path:
    return Path(root).expanduser().resolve()


def _video_root(root: Path | str) -> Path:
    return _root(root) / "videos"


def _safe_export_id(export_id: str) -> str:
    value = str(export_id or "").strip()
    if not _SAFE_ID_RE.fullmatch(value):
        raise ValueError("invalid export id")
    return value


def _validate_kind(kind: str) -> str:
    value = str(kind or "").strip()
    if value not in _ALLOWED_KINDS:
        raise ValueError("kind must be realtime_dialogue, video_clone, or video_creation")
    return value


def _extension_for_mime(mime_type: str) -> str:
    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    return _MIME_EXTENSIONS.get(normalized, ".webm")


def _metadata_path_for_export(root: Path | str, export_id: str) -> Path | None:
    safe_id = _safe_export_id(export_id)
    base = _video_root(root)
    if not base.is_dir():
        return None
    for metadata_path in base.glob(f"*/{safe_id}/metadata.json"):
        resolved = metadata_path.resolve()
        try:
            resolved.relative_to(base.resolve())
        except ValueError:
            continue
        return resolved
    return None


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _read_metadata(path: Path, root: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    file_path = Path(str(raw.get("path") or "")).expanduser().resolve()
    try:
        file_path.relative_to(root.resolve())
    except ValueError:
        return None
    if not file_path.is_file():
        return None
    raw["path"] = str(file_path)
    return raw


def create_video_export(
    root: Path | str,
    *,
    content: bytes,
    mime_type: str,
    kind: str,
    title: str,
    duration_sec: float | None,
    session_id: str | None,
    avatar_id: str | None,
    model: str | None,
    max_bytes: int,
    created_at: str | None = None,
) -> dict[str, Any]:
    data = bytes(content)
    if len(data) > max(0, int(max_bytes)):
        raise ExportTooLargeError("export video is too large")
    normalized_kind = _validate_kind(kind)
    created = created_at or _utc_now()
    try:
        day = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
    export_id = uuid.uuid4().hex
    target_dir = (_video_root(root) / day / export_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=False)
    try:
        target_dir.relative_to(_video_root(root).resolve())
    except ValueError as exc:
        raise ValueError("invalid export path") from exc
    ext = _extension_for_mime(mime_type)
    file_path = target_dir / f"recording{ext}"
    file_path.write_bytes(data)
    item: dict[str, Any] = {
        "id": export_id,
        "kind": normalized_kind,
        "title": title.strip() or "Untitled export",
        "duration_sec": duration_sec,
        "size_bytes": len(data),
        "mime_type": (mime_type or "application/octet-stream").split(";", 1)[0].strip() or "application/octet-stream",
        "created_at": created,
        "path": str(file_path.resolve()),
        "session_id": _normalize_optional_text(session_id),
        "avatar_id": _normalize_optional_text(avatar_id),
        "model": _normalize_optional_text(model),
    }
    (target_dir / "metadata.json").write_text(
        json.dumps(item, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return item


def list_video_exports(
    root: Path | str,
    *,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    base = _video_root(root).resolve()
    if not base.is_dir():
        return []
    normalized_kind = _validate_kind(kind) if kind else None
    items: list[dict[str, Any]] = []
    for metadata_path in base.glob("*/*/metadata.json"):
        item = _read_metadata(metadata_path, _root(root))
        if item is None:
            continue
        if normalized_kind and item.get("kind") != normalized_kind:
            continue
        items.append(item)
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    start = max(0, int(offset))
    stop = start + max(0, min(int(limit), 200))
    return items[start:stop]


def get_video_export(root: Path | str, export_id: str) -> dict[str, Any] | None:
    metadata_path = _metadata_path_for_export(root, export_id)
    if metadata_path is None:
        return None
    return _read_metadata(metadata_path, _root(root))


def delete_video_export(root: Path | str, export_id: str) -> bool:
    metadata_path = _metadata_path_for_export(root, export_id)
    if metadata_path is None:
        return False
    export_dir = metadata_path.parent.resolve()
    try:
        export_dir.relative_to(_video_root(root).resolve())
    except ValueError as exc:
        raise ValueError("invalid export path") from exc
    shutil.rmtree(export_dir)
    return True
