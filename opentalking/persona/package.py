from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from opentalking.agent.knowledge_store import KnowledgeStore
from opentalking.persona.schema import PersonaManifest, load_persona_manifest, write_persona_manifest
from opentalking.persona.store import PersonaRecord, PersonaStore


PERSONA_PACKAGE_SUFFIX = ".otpersona"
_MAX_PACKAGE_BYTES = 200 * 1024 * 1024


def _safe_zip_member(name: str) -> bool:
    path = Path(name)
    if path.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    return True


def _ensure_safe_zip(path: Path) -> None:
    total = 0
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if "persona.json" not in names:
            raise ValueError("persona package missing persona.json")
        for info in zf.infolist():
            if not _safe_zip_member(info.filename):
                raise ValueError(f"unsafe persona package path: {info.filename}")
            total += int(info.file_size)
            if total > _MAX_PACKAGE_BYTES:
                raise ValueError("persona package is larger than 200MB")


def extract_persona_package(package_path: str | Path, target_dir: str | Path) -> PersonaManifest:
    src = Path(package_path)
    if not src.is_file():
        raise ValueError("persona package not found")
    _ensure_safe_zip(src)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        zf.extractall(target)
    return load_persona_manifest(target / "persona.json")


def validate_persona_package(package_path: str | Path) -> PersonaManifest:
    with tempfile.TemporaryDirectory(prefix="opentalking-persona-validate-") as tmp:
        return extract_persona_package(package_path, tmp)


def _read_prompt_text(root: Path, rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    path = (root / rel_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("prompt path must stay inside persona package") from exc
    if not path.is_file():
        raise ValueError(f"prompt file not found: {rel_path}")
    return path.read_text(encoding="utf-8").strip()


def _find_knowledge_files(root: Path) -> list[Path]:
    knowledge_root = root / "knowledge"
    if not knowledge_root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(knowledge_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "manifest.json":
            continue
        files.append(path)
    return files


async def _import_knowledge_documents(
    *,
    manifest: PersonaManifest,
    package_root: Path,
    knowledge_store: KnowledgeStore | None,
) -> PersonaManifest:
    files = _find_knowledge_files(package_root)
    if not files or knowledge_store is None:
        return manifest
    knowledge_base = await knowledge_store.create_knowledge_base(f"{manifest.name} Knowledge")
    for path in files:
        await knowledge_store.add_document(
            kb_id=knowledge_base.id,
            filename=path.name,
            mime_type=_mime_type_for(path),
            source_path=path,
        )
    return replace(
        manifest,
        agent=replace(
            manifest.agent,
            knowledge_enabled=True,
            knowledge_base_ids=[knowledge_base.id],
        ),
    )


def _mime_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return "application/octet-stream"


async def import_persona_package(
    package_path: str | Path,
    *,
    store: PersonaStore,
    knowledge_store: KnowledgeStore | None = None,
) -> PersonaRecord:
    with tempfile.TemporaryDirectory(prefix="opentalking-persona-import-") as tmp:
        package_root = Path(tmp)
        manifest = extract_persona_package(package_path, package_root)
        _read_prompt_text(package_root, manifest.agent.persona_prompt)
        system_prompt = _read_prompt_text(package_root, manifest.agent.system_prompt)
        style_prompt = _read_prompt_text(package_root, manifest.agent.style_prompt)
        if system_prompt or style_prompt:
            combined_prompt = "\n\n".join(
                part for part in [system_prompt, style_prompt] if part
            )
            (package_root / "prompts" / "_compiled_system.md").parent.mkdir(parents=True, exist_ok=True)
            (package_root / "prompts" / "_compiled_system.md").write_text(
                combined_prompt + "\n",
                encoding="utf-8",
            )
            manifest = replace(
                manifest,
                agent=replace(
                    manifest.agent,
                    system_prompt="prompts/_compiled_system.md",
                    style_prompt=None,
                ),
            )
        manifest = await _import_knowledge_documents(
            manifest=manifest,
            package_root=package_root,
            knowledge_store=knowledge_store,
        )
        write_persona_manifest(package_root / "persona.json", manifest)
        return store.save_persona(manifest, source_dir=package_root, source="package", replace=True)


def export_persona_package(
    persona_id: str,
    *,
    store: PersonaStore,
    out_path: str | Path,
) -> Path:
    record = store.get_persona(persona_id)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_files(record.path):
            if path.name == ".persona-meta.json":
                continue
            zf.write(path, path.relative_to(record.path).as_posix())
    return target


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def create_persona_package_from_dir(source_dir: str | Path, out_path: str | Path) -> Path:
    source = Path(source_dir)
    load_persona_manifest(source / "persona.json")
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_files(source):
            zf.write(path, path.relative_to(source).as_posix())
    return target


def copy_persona_source(source_dir: str | Path, target_dir: str | Path) -> PersonaManifest:
    source = Path(source_dir)
    manifest = load_persona_manifest(source / "persona.json")
    target = Path(target_dir)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return manifest


def persona_record_json(record: PersonaRecord) -> str:
    return json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
