from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from opentalking.persona.schema import PersonaManifest, load_persona_manifest, validate_persona_id, write_persona_manifest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class PersonaRecord:
    manifest: PersonaManifest
    path: Path
    created_at: str
    updated_at: str
    source: str = "local"

    def to_dict(self) -> dict[str, object]:
        return {
            **self.manifest.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
        }


class PersonaStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _persona_dir(self, persona_id: str) -> Path:
        clean = validate_persona_id(persona_id)
        return self.root / clean

    def list_personas(self) -> list[PersonaRecord]:
        if not self.root.is_dir():
            return []
        records: list[PersonaRecord] = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "persona.json"
            if not manifest_path.is_file():
                continue
            try:
                records.append(self.get_persona(child.name))
            except Exception:
                continue
        return records

    def get_persona(self, persona_id: str) -> PersonaRecord:
        persona_dir = self._persona_dir(persona_id)
        manifest_path = persona_dir / "persona.json"
        if not manifest_path.is_file():
            raise KeyError("persona not found")
        manifest = load_persona_manifest(manifest_path)
        meta = self._read_meta(persona_dir)
        stat = manifest_path.stat()
        created_at = str(meta.get("created_at") or _datetime_from_ts(stat.st_ctime))
        updated_at = str(meta.get("updated_at") or _datetime_from_ts(stat.st_mtime))
        source = str(meta.get("source") or "local")
        return PersonaRecord(
            manifest=manifest,
            path=persona_dir,
            created_at=created_at,
            updated_at=updated_at,
            source=source,
        )

    def save_persona(
        self,
        manifest: PersonaManifest,
        *,
        source_dir: str | Path | None = None,
        source: str = "local",
        replace: bool = True,
    ) -> PersonaRecord:
        persona_dir = self._persona_dir(manifest.id)
        if persona_dir.exists() and not replace:
            raise FileExistsError("persona already exists")
        self.root.mkdir(parents=True, exist_ok=True)
        if source_dir is not None:
            src = Path(source_dir)
            tmp_dir = persona_dir.with_name(f".{persona_dir.name}.tmp")
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
            shutil.copytree(src, tmp_dir)
            write_persona_manifest(tmp_dir / "persona.json", manifest)
            now = _utc_now()
            self._write_meta(tmp_dir, created_at=now, updated_at=now, source=source)
            if persona_dir.exists():
                shutil.rmtree(persona_dir)
            tmp_dir.rename(persona_dir)
        else:
            persona_dir.mkdir(parents=True, exist_ok=True)
            previous_created_at = None
            try:
                previous_created_at = self._read_meta(persona_dir).get("created_at")
            except Exception:
                previous_created_at = None
            write_persona_manifest(persona_dir / "persona.json", manifest)
            now = _utc_now()
            self._write_meta(
                persona_dir,
                created_at=str(previous_created_at or now),
                updated_at=now,
                source=source,
            )
        return self.get_persona(manifest.id)

    def delete_persona(self, persona_id: str) -> bool:
        persona_dir = self._persona_dir(persona_id)
        if not persona_dir.is_dir():
            return False
        shutil.rmtree(persona_dir)
        return True

    def _read_meta(self, persona_dir: Path) -> dict[str, object]:
        path = persona_dir / ".persona-meta.json"
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_meta(self, persona_dir: Path, *, created_at: str, updated_at: str, source: str) -> None:
        persona_dir.mkdir(parents=True, exist_ok=True)
        (persona_dir / ".persona-meta.json").write_text(
            json.dumps(
                {"created_at": created_at, "updated_at": updated_at, "source": source},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def _datetime_from_ts(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
