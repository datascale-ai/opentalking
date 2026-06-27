from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from opentalking.core.config import get_settings
from opentalking.providers.memory.schemas import MemoryItem, utc_now_iso
from opentalking.persona.weflow_parser import WeFlowExport, WeFlowSpeaker, WeFlowTurn


class PersonaLLMClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str | Awaitable[str]: ...


@dataclass(frozen=True)
class WeChatPersonaDraft:
    target_speaker: WeFlowSpeaker
    persona_name: str
    persona_md: str
    memory_items: list[MemoryItem]
    source_metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class _ConfiguredPersonaLLM:
    async def complete(self, messages: list[dict[str, str]]) -> str:
        settings = get_settings()
        if not str(getattr(settings, "llm_base_url", "") or "").strip():
            return ""
        from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient

        client = OpenAICompatibleLLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
        chunks: list[str] = []
        async for chunk in client.chat_stream(messages):
            chunks.append(chunk)
        return "".join(chunks)


def build_wechat_persona_draft(
    export: WeFlowExport,
    *,
    target_speaker_id: str | None = None,
    llm_client: PersonaLLMClient | None = None,
    max_sample_turns: int = 80,
) -> WeChatPersonaDraft:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            build_wechat_persona_draft_async(
                export,
                target_speaker_id=target_speaker_id,
                llm_client=llm_client,
                max_sample_turns=max_sample_turns,
            )
        )
    raise RuntimeError("build_wechat_persona_draft_async must be used inside a running event loop")


async def build_wechat_persona_draft_async(
    export: WeFlowExport,
    *,
    target_speaker_id: str | None = None,
    llm_client: PersonaLLMClient | None = None,
    max_sample_turns: int = 80,
) -> WeChatPersonaDraft:
    target = _resolve_target_speaker(export, target_speaker_id)
    target_turns = [turn for turn in export.turns if turn.speaker_id == target.id]
    if not target_turns:
        raise ValueError("target speaker has no readable messages")
    limited_turns = target_turns[: max(1, max_sample_turns)]
    source_metadata = {
        "source": "wechat_import",
        "source_format": export.detected_format,
        "source_name": export.source_metadata.get("source_name"),
        "conversation_id": export.conversation_id,
        "target_speaker_id": target.id,
        "target_speaker_name": target.name,
        "target_message_count": len(target_turns),
    }
    warnings = list(export.warnings)

    client = llm_client or _ConfiguredPersonaLLM()
    llm_payload = await _try_llm_build(client, target=target, turns=limited_turns)
    if llm_payload:
        draft = _draft_from_llm_payload(
            llm_payload,
            target=target,
            source_metadata=source_metadata,
            warnings=warnings,
        )
        if draft is not None:
            return draft
        warnings.append("llm_payload_invalid")

    return _fallback_draft(target=target, turns=limited_turns, source_metadata=source_metadata, warnings=warnings)


def _resolve_target_speaker(export: WeFlowExport, target_speaker_id: str | None) -> WeFlowSpeaker:
    if target_speaker_id:
        for speaker in export.speakers:
            if speaker.id == target_speaker_id:
                return speaker
        raise ValueError("target speaker not found")
    candidates = [speaker for speaker in export.speakers if not speaker.is_self]
    if not candidates:
        candidates = list(export.speakers)
    if not candidates:
        raise ValueError("WeFlow export has no speakers")
    return sorted(candidates, key=lambda item: (-item.message_count, item.name))[0]


async def _try_llm_build(
    client: PersonaLLMClient,
    *,
    target: WeFlowSpeaker,
    turns: Sequence[WeFlowTurn],
) -> dict[str, Any] | None:
    transcript = "\n".join(
        f"- {turn.timestamp or 'unknown'} {target.name}: {_redact_sensitive(turn.content)[:240]}"
        for turn in turns
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You extract a digital-human persona from a user-uploaded WeChat export. "
                "Return strict JSON with keys persona_md, style_memories, semantic_memories, "
                "episodic_summaries, confidence. Summarize style and persona traits; do not copy "
                "raw private transcript lines or secrets."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Target speaker: {target.name} ({target.id})\n"
                f"Sample target-speaker messages, redacted:\n{transcript}"
            ),
        },
    ]
    try:
        result = client.complete(messages)
        raw = result if isinstance(result, str) else await result
    except Exception:
        return None
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _draft_from_llm_payload(
    payload: dict[str, Any],
    *,
    target: WeFlowSpeaker,
    source_metadata: dict[str, Any],
    warnings: list[str],
) -> WeChatPersonaDraft | None:
    persona_md = _safe_text(str(payload.get("persona_md") or "").strip())
    if not persona_md:
        return None
    confidence = _confidence(str(payload.get("confidence") or "medium"))
    items: list[MemoryItem] = []
    for text in _string_list(payload.get("style_memories")):
        items.append(_memory_item(text, kind="preference", layer="style", target=target, confidence=confidence))
    for text in _string_list(payload.get("semantic_memories")):
        items.append(_memory_item(text, kind="note", layer="semantic", target=target, confidence=confidence))
    for text in _string_list(payload.get("episodic_summaries")):
        items.append(_memory_item(text, kind="summary", layer="episodic", target=target, confidence=confidence))
    if not items:
        return None
    return WeChatPersonaDraft(
        target_speaker=target,
        persona_name=target.name,
        persona_md=persona_md,
        memory_items=items,
        source_metadata=source_metadata,
        warnings=warnings,
    )


def _fallback_draft(
    *,
    target: WeFlowSpeaker,
    turns: Sequence[WeFlowTurn],
    source_metadata: dict[str, Any],
    warnings: list[str],
) -> WeChatPersonaDraft:
    stats = _style_stats(turns)
    persona_md = "\n".join(
        [
            "# Persona",
            f"Name: {target.name}",
            "Origin: Built from a user-uploaded WeFlow WeChat export.",
            "",
            "# Speaking Style",
            f"- Uses a {stats['length_label']} reply rhythm with calm, practical guidance.",
            "- Favors small next steps, check-ins, and emotionally steady phrasing.",
            "- Avoids exposing raw imported chat lines; use this as a style guide, not a transcript.",
            "",
            "# Memory Policy",
            "- Treat imported chat records as private source artifacts.",
            "- Runtime prompts should load this persona.md summary, never raw chat logs.",
        ]
    )
    style = f"{target.name} tends to use {stats['length_label']} replies with calm practical guidance."
    semantic = f"Persona source contains {len(turns)} target-speaker WeChat messages imported from WeFlow."
    episodic = f"Imported chats suggest {target.name} often supports planning, check-ins, or emotional steadiness."
    return WeChatPersonaDraft(
        target_speaker=target,
        persona_name=target.name,
        persona_md=persona_md,
        memory_items=[
            _memory_item(style, kind="preference", layer="style", target=target, confidence="medium"),
            _memory_item(semantic, kind="note", layer="semantic", target=target, confidence="medium"),
            _memory_item(episodic, kind="summary", layer="episodic", target=target, confidence="medium"),
        ],
        source_metadata=source_metadata,
        warnings=warnings,
    )


def _style_stats(turns: Sequence[WeFlowTurn]) -> dict[str, str]:
    contents = [_redact_sensitive(turn.content) for turn in turns if turn.content.strip()]
    if not contents:
        return {"length_label": "concise"}
    avg_words = sum(max(1, len(text.split())) for text in contents) / len(contents)
    if avg_words <= 8:
        label = "concise"
    elif avg_words <= 20:
        label = "balanced"
    else:
        label = "detailed"
    return {"length_label": label}


def _memory_item(
    text: str,
    *,
    kind: str,
    layer: str,
    target: WeFlowSpeaker,
    confidence: str,
) -> MemoryItem:
    clean = _safe_text(text)
    return MemoryItem(
        id="",
        text=clean,
        type=kind,  # type: ignore[arg-type]
        metadata={
            "source": "wechat_import",
            "source_type": "weflow_upload",
            "layer": layer,
            "target_speaker_id": target.id,
            "target_speaker_name": target.name,
            "confidence": _confidence(confidence),
        },
        created_at=utc_now_iso(),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _safe_text(str(item or "").strip())
        if text:
            out.append(text)
    return out


def _confidence(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"low", "medium", "high"}:
        return normalized
    return "medium"


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _safe_text(text: str) -> str:
    return _redact_sensitive(text).strip()


def _redact_sensitive(text: str) -> str:
    redacted = re.sub(r"\b\d{4,}\b", "[redacted-number]", text)
    redacted = re.sub(r"(?i)\b(secret|password|token|api[_ -]?key)\b[^.\n;]*", "[redacted-sensitive]", redacted)
    return redacted
