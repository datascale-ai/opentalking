from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

DUO_DIALOG_ROLES = {"male", "female"}
DUO_DIALOG_POSITION_ROLES = {"left", "right"}
DEFAULT_DUO_DIALOG_GAP_MS = 120
MAX_DUO_DIALOG_GAP_MS = 5000


def _string_mapping(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        clean_key = str(key or "").strip()
        clean_value = str(value or "").strip()
        if clean_key and clean_value:
            out[clean_key] = clean_value
    return out


def _clean_string(raw: object) -> str | None:
    value = str(raw or "").strip()
    return value or None


def _speaker_tts_mapping(raw: object) -> dict[str, dict[str, object]]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, dict[str, object]] = {}
    for role_raw, config_raw in raw.items():
        role = str(role_raw or "").strip()
        if not role or not isinstance(config_raw, Mapping):
            continue
        config: dict[str, object] = {}
        for source_key, target_key in (
            ("tts_provider", "tts_provider"),
            ("provider", "tts_provider"),
            ("tts_model", "tts_model"),
            ("model", "tts_model"),
            ("voice", "voice"),
            ("voice_id", "voice"),
        ):
            value = _clean_string(config_raw.get(source_key))
            if value:
                config[target_key] = value
        indextts_config = config_raw.get("indextts_config")
        if isinstance(indextts_config, Mapping):
            config["indextts_config"] = dict(indextts_config)
        if config:
            out[role] = config
    return out


def _position_role_aliases(speaker_faces: Mapping[str, str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for role, face in speaker_faces.items():
        clean_role = str(role or "").strip()
        clean_face = str(face or "").strip()
        if clean_role and clean_face in DUO_DIALOG_POSITION_ROLES:
            aliases[clean_face] = clean_role
    return aliases


def _normalize_role_mappings_to_payload(
    payload: Mapping[str, Any],
    *,
    speaker_faces: dict[str, str],
    default_voices: dict[str, str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    raw_lines = payload.get("lines")
    requested_roles: set[str] = set()
    if isinstance(raw_lines, Sequence) and not isinstance(raw_lines, (str, bytes)):
        for raw_line in raw_lines:
            if isinstance(raw_line, Mapping):
                role = str(raw_line.get("role") or "").strip()
                if role:
                    requested_roles.add(role)
    for raw_mapping in (payload.get("voices"), payload.get("speakers")):
        if isinstance(raw_mapping, Mapping):
            requested_roles.update(str(role or "").strip() for role in raw_mapping.keys() if str(role or "").strip())

    if not requested_roles or requested_roles.issubset(set(speaker_faces)):
        return speaker_faces, default_voices, {}

    aliases = _position_role_aliases(speaker_faces)
    if not aliases or not requested_roles.issubset(set(speaker_faces) | set(aliases)):
        return speaker_faces, default_voices, {}

    normalized_faces = {role: speaker_faces[role] for role in requested_roles if role in speaker_faces}
    normalized_voices = dict(default_voices)
    role_aliases: dict[str, str] = {}
    for requested_role in requested_roles:
        if requested_role in normalized_faces:
            continue
        legacy_role = aliases.get(requested_role)
        if not legacy_role:
            continue
        normalized_faces[requested_role] = requested_role
        if legacy_role in normalized_voices and requested_role not in normalized_voices:
            normalized_voices[requested_role] = normalized_voices[legacy_role]
        role_aliases[requested_role] = legacy_role
    return normalized_faces, normalized_voices, role_aliases


def duo_dialog_summary_from_metadata(metadata: Mapping[str, Any] | None) -> dict[str, object] | None:
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get("duo_dialog")
    if not isinstance(raw, Mapping):
        return None
    speaker_faces = _string_mapping(raw.get("speaker_faces"))
    if not speaker_faces:
        return None
    default_voices = _string_mapping(raw.get("default_voices"))
    return {"speaker_faces": speaker_faces, "default_voices": default_voices}


def _coerce_gap_ms(raw: object) -> int:
    if raw in (None, ""):
        return DEFAULT_DUO_DIALOG_GAP_MS
    if not isinstance(raw, str | int | float):
        raise ValueError("duo_dialog.gap_ms must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("duo_dialog.gap_ms must be an integer") from exc
    if value < 0 or value > MAX_DUO_DIALOG_GAP_MS:
        raise ValueError(f"duo_dialog.gap_ms must be between 0 and {MAX_DUO_DIALOG_GAP_MS}")
    return value


def normalize_duo_dialog_payload(
    payload: Mapping[str, Any],
    *,
    speaker_faces: Mapping[str, str],
    default_voices: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("duo_dialog must be a JSON object")
    faces = _string_mapping(speaker_faces)
    if not faces:
        raise ValueError("avatar duo_dialog speaker_faces is required")
    default_voice_map = _string_mapping(default_voices or {})
    faces, default_voice_map, role_aliases = _normalize_role_mappings_to_payload(
        payload,
        speaker_faces=faces,
        default_voices=default_voice_map,
    )

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, Sequence) or isinstance(raw_lines, (str, bytes)):
        raise ValueError("duo_dialog.lines must be a non-empty list")
    if not raw_lines:
        raise ValueError("duo_dialog.lines must be a non-empty list")

    lines: list[dict[str, str]] = []
    for index, raw_line in enumerate(raw_lines, start=1):
        if not isinstance(raw_line, Mapping):
            raise ValueError("duo_dialog.lines must contain objects")
        role = str(raw_line.get("role") or "").strip()
        if role not in faces:
            raise ValueError(f"invalid duo_dialog role: {role or index}")
        text = str(raw_line.get("text") or "").strip()
        if not text:
            raise ValueError("duo_dialog line text is required")
        line_id = str(raw_line.get("id") or f"line-{index}").strip() or f"line-{index}"
        lines.append({"id": line_id, "role": role, "text": text})

    voices = dict(default_voice_map)
    voices.update(_string_mapping(payload.get("voices")))
    speakers = _speaker_tts_mapping(payload.get("speakers"))
    normalized_speakers: dict[str, dict[str, object]] = {}
    for role in {line["role"] for line in lines}:
        config = dict(speakers.get(role) or {})
        if not config:
            config = dict(speakers.get(role_aliases.get(role, "")) or {})
        if not config.get("voice") and voices.get(role):
            config["voice"] = voices[role]
        if config.get("voice"):
            voices[role] = str(config["voice"])
        if not config.get("voice") and not config.get("tts_provider"):
            raise ValueError(f"voice is required for duo_dialog role: {role}")
        normalized_speakers[role] = config

    return {
        "lines": lines,
        "voices": voices,
        "speakers": normalized_speakers,
        "speaker_faces": faces,
        "gap_ms": _coerce_gap_ms(payload.get("gap_ms")),
    }
