from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PERSONA_SCHEMA_VERSION = "1.0"
SUPPORTED_PERSONA_SCHEMA_VERSIONS = {PERSONA_SCHEMA_VERSION, "0.1"}
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")


@dataclass(frozen=True)
class PersonaAvatar:
    id: str
    model: str
    path: str | None = None


@dataclass(frozen=True)
class PersonaVoice:
    provider: str | None = None
    voice_id: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class PersonaAgent:
    persona_prompt: str | None = None
    system_prompt: str | None = None
    style_prompt: str | None = None
    memory_enabled: bool = False
    knowledge_enabled: bool = True
    knowledge_base_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaRuntime:
    stt_provider: str | None = None
    tts_provider: str | None = None
    preferred_backend: str | None = None


@dataclass(frozen=True)
class PersonaSafety:
    authorized_avatar: bool = False
    authorized_voice: bool = False
    content_label_required: bool = True


@dataclass(frozen=True)
class PersonaManifest:
    schema_version: str
    id: str
    name: str
    description: str
    locale: str
    avatar: PersonaAvatar
    voice: PersonaVoice = field(default_factory=PersonaVoice)
    agent: PersonaAgent = field(default_factory=PersonaAgent)
    runtime: PersonaRuntime = field(default_factory=PersonaRuntime)
    safety: PersonaSafety = field(default_factory=PersonaSafety)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_persona_id(persona_id: str) -> str:
    clean = (persona_id or "").strip()
    if not _SAFE_ID_RE.fullmatch(clean):
        raise ValueError("persona id must start with a letter or digit and contain only letters, digits, _ or -")
    return clean


def _optional_str(raw: Any, *, max_len: int = 4096) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    return value[:max_len]


def _required_str(raw: Any, field_name: str, *, max_len: int = 4096) -> str:
    value = _optional_str(raw, max_len=max_len)
    if value is None:
        raise ValueError(f"persona missing field: {field_name}")
    return value


def _bool(raw: Any, *, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("knowledge_base_ids must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        out.append(value[:80])
        seen.add(value)
    return out


def _object(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def persona_from_dict(raw: dict[str, Any]) -> PersonaManifest:
    if not isinstance(raw, dict):
        raise ValueError("persona manifest must be a JSON object")
    schema_version = _required_str(raw.get("schema_version"), "schema_version", max_len=16)
    if schema_version not in SUPPORTED_PERSONA_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported persona schema_version: {schema_version}")
    persona_id = validate_persona_id(_required_str(raw.get("id"), "id", max_len=80))
    avatar_raw = raw.get("avatar")
    if not isinstance(avatar_raw, dict):
        raise ValueError("persona missing field: avatar")
    avatar = PersonaAvatar(
        id=_required_str(avatar_raw.get("id"), "avatar.id", max_len=80),
        model=_required_str(avatar_raw.get("model"), "avatar.model", max_len=80),
        path=_optional_str(avatar_raw.get("path"), max_len=256),
    )

    voice_raw = _object(raw.get("voice"))
    agent_raw = _object(raw.get("agent"))
    runtime_raw = _object(raw.get("runtime"))
    safety_raw = _object(raw.get("safety"))

    return PersonaManifest(
        schema_version=PERSONA_SCHEMA_VERSION,
        id=persona_id,
        name=_required_str(raw.get("name"), "name", max_len=160),
        description=_required_str(raw.get("description"), "description", max_len=2000),
        locale=_required_str(raw.get("locale"), "locale", max_len=32),
        avatar=avatar,
        voice=PersonaVoice(
            provider=_optional_str(voice_raw.get("provider"), max_len=80),
            voice_id=_optional_str(voice_raw.get("voice_id"), max_len=256),
            model=_optional_str(voice_raw.get("model"), max_len=256),
        ),
        agent=PersonaAgent(
            persona_prompt=_optional_str(agent_raw.get("persona_prompt"), max_len=256),
            system_prompt=_optional_str(agent_raw.get("system_prompt"), max_len=256),
            style_prompt=_optional_str(agent_raw.get("style_prompt"), max_len=256),
            memory_enabled=_bool(agent_raw.get("memory_enabled"), default=False),
            knowledge_enabled=_bool(agent_raw.get("knowledge_enabled"), default=True),
            knowledge_base_ids=_string_list(agent_raw.get("knowledge_base_ids")),
        ),
        runtime=PersonaRuntime(
            stt_provider=_optional_str(runtime_raw.get("stt_provider"), max_len=80),
            tts_provider=_optional_str(runtime_raw.get("tts_provider"), max_len=80),
            preferred_backend=_optional_str(runtime_raw.get("preferred_backend"), max_len=80),
        ),
        safety=PersonaSafety(
            authorized_avatar=_bool(safety_raw.get("authorized_avatar"), default=False),
            authorized_voice=_bool(safety_raw.get("authorized_voice"), default=False),
            content_label_required=_bool(safety_raw.get("content_label_required"), default=True),
        ),
    )


def load_persona_manifest(path: str | Path) -> PersonaManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return persona_from_dict(raw)


def write_persona_manifest(path: str | Path, manifest: PersonaManifest) -> None:
    Path(path).write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
