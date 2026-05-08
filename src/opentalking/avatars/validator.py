from __future__ import annotations

from pathlib import Path

from opentalking.avatars.manifest import parse_manifest


def validate_avatar_dir(avatar_dir: Path) -> list[str]:
    """Return list of validation errors; empty means OK."""
    errors: list[str] = []
    if not avatar_dir.is_dir():
        return [f"not a directory: {avatar_dir}"]
    manifest_path = avatar_dir / "manifest.json"
    if not manifest_path.is_file():
        errors.append("missing manifest.json")
        return errors
    try:
        m = parse_manifest(manifest_path)
    except Exception as e:  # noqa: BLE001
        errors.append(f"invalid manifest: {e}")
        return errors

    preview = avatar_dir / "preview.png"
    if not preview.is_file():
        errors.append("missing preview.png (recommended)")

    if m.model_type == "musetalk":
        ff = avatar_dir / "full_frames"
        if not ff.is_dir():
            errors.append("musetalk avatar should have full_frames/ directory")
        elif not any(ff.iterdir()):
            errors.append("full_frames/ is empty")
    elif m.model_type in {"flashtalk", "flashhead"}:
        if not (avatar_dir / "reference.png").is_file() and not (avatar_dir / "reference.jpg").is_file():
            errors.append(f"{m.model_type} avatar should have reference.png or reference.jpg")
    elif m.model_type == "wav2lip":
        frames = avatar_dir / "frames"
        if not frames.is_dir():
            errors.append("wav2lip avatar should have frames/ directory")
    elif m.model_type == "quicktalk":
        metadata = m.metadata or {}
        if not metadata.get("template_video"):
            errors.append("quicktalk avatar should define metadata.template_video")
        if not metadata.get("asset_root"):
            errors.append("quicktalk avatar should define metadata.asset_root")

    return errors


def assert_valid_avatar_dir(avatar_dir: Path) -> None:
    errs = validate_avatar_dir(avatar_dir)
    if errs:
        raise ValueError("; ".join(errs))


def list_avatar_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "manifest.json").is_file():
            out.append(child)
    return out
