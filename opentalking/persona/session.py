from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opentalking.persona.persona_md import build_persona_prompt_text
from opentalking.persona.store import PersonaRecord, PersonaStore


@dataclass(frozen=True)
class PersonaSessionDefaults:
    persona_id: str
    avatar_id: str
    model: str
    tts_provider: str | None
    stt_provider: str | None
    tts_voice: str | None
    tts_model: str | None
    llm_system_prompt: str | None
    memory_enabled: bool
    knowledge_enabled: bool
    knowledge_base_ids: list[str]


def default_persona_store() -> PersonaStore:
    from opentalking.core.config import get_settings

    return PersonaStore(Path(get_settings().persona_root))


def build_session_defaults(record: PersonaRecord) -> PersonaSessionDefaults:
    manifest = record.manifest
    prompt = build_persona_prompt_text(
        record.path,
        persona_prompt=manifest.agent.persona_prompt,
        system_prompt=manifest.agent.system_prompt,
        style_prompt=manifest.agent.style_prompt,
    )
    return PersonaSessionDefaults(
        persona_id=manifest.id,
        avatar_id=manifest.avatar.id,
        model=manifest.avatar.model,
        tts_provider=manifest.runtime.tts_provider or manifest.voice.provider,
        stt_provider=manifest.runtime.stt_provider,
        tts_voice=manifest.voice.voice_id,
        tts_model=manifest.voice.model,
        llm_system_prompt=prompt,
        memory_enabled=manifest.agent.memory_enabled,
        knowledge_enabled=manifest.agent.knowledge_enabled,
        knowledge_base_ids=list(manifest.agent.knowledge_base_ids),
    )


def load_session_defaults(persona_id: str, *, store: PersonaStore | None = None) -> PersonaSessionDefaults:
    persona_store = store or default_persona_store()
    return build_session_defaults(persona_store.get_persona(persona_id))


def _read_prompt(root: Path, rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    path = (root / rel_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None
