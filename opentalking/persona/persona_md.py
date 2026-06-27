from __future__ import annotations

from pathlib import Path

from opentalking.persona.store import PersonaRecord


DEFAULT_PERSONA_MD = "persona.md"


def _safe_relative_path(root: Path, rel_path: str | None, *, field_name: str) -> Path:
    value = (rel_path or DEFAULT_PERSONA_MD).strip() or DEFAULT_PERSONA_MD
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field_name} path must stay inside persona directory") from exc
    return path


def read_prompt_file(root: Path, rel_path: str | None, *, field_name: str) -> str | None:
    if not rel_path:
        return None
    path = _safe_relative_path(root, rel_path, field_name=field_name)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def read_persona_md(record: PersonaRecord) -> str:
    path = _safe_relative_path(
        record.path,
        record.manifest.agent.persona_prompt or DEFAULT_PERSONA_MD,
        field_name="persona_prompt",
    )
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_persona_md(record: PersonaRecord, content: str) -> str:
    path = _safe_relative_path(
        record.path,
        record.manifest.agent.persona_prompt or DEFAULT_PERSONA_MD,
        field_name="persona_prompt",
    )
    text = str(content or "").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return text


def build_persona_prompt_text(
    root: Path,
    *,
    persona_prompt: str | None,
    system_prompt: str | None,
    style_prompt: str | None,
) -> str | None:
    parts = [
        read_prompt_file(root, persona_prompt, field_name="persona_prompt"),
        read_prompt_file(root, system_prompt, field_name="system_prompt"),
        read_prompt_file(root, style_prompt, field_name="style_prompt"),
    ]
    combined = "\n\n".join(part for part in parts if part)
    return combined or None
