"""MiniMax voice-cloning API client."""

from __future__ import annotations

import re
from typing import Any

import httpx


MINIMAX_VOICE_CLONE_MODELS = (
    "speech-2.8-hd",
    "speech-2.6-hd",
    "speech-02-hd",
    "speech-01-hd",
)

_REGION_BASE_URLS = {
    "global": "https://api.minimax.io/v1",
    "cn": "https://api.minimaxi.com/v1",
}
_VOICE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{7,255}$")


class MiniMaxVoiceCloneError(RuntimeError):
    """Raised when the voice-cloning API rejects a request."""


def resolve_minimax_base_url(*, region: str = "global", base_url: str = "") -> str:
    """Resolve an explicit API base URL or a supported regional endpoint."""
    if base_url.strip():
        return base_url.strip().rstrip("/")
    normalized_region = region.strip().lower() or "global"
    try:
        return _REGION_BASE_URLS[normalized_region]
    except KeyError as exc:
        raise ValueError("MiniMax region must be 'global' or 'cn'") from exc


def _validate_voice_id(voice_id: str) -> str:
    normalized = voice_id.strip()
    if not _VOICE_ID_RE.fullmatch(normalized):
        raise ValueError(
            "MiniMax voice_id must be 8-256 characters, start with a letter, "
            "and contain only letters, numbers, hyphens, or underscores"
        )
    return normalized


def _parse_response(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise MiniMaxVoiceCloneError(
            f"MiniMax {operation} failed with HTTP {response.status_code}"
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise MiniMaxVoiceCloneError(f"MiniMax {operation} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise MiniMaxVoiceCloneError(f"MiniMax {operation} returned an invalid response")
    base_response = payload.get("base_resp")
    if isinstance(base_response, dict):
        status_code = base_response.get("status_code")
        if status_code not in (None, 0, "0"):
            message = str(base_response.get("status_msg") or "request rejected")
            raise MiniMaxVoiceCloneError(f"MiniMax {operation} failed: {message}")
    return payload


async def clone_minimax_voice(
    *,
    wav_bytes: bytes,
    voice_id: str,
    model: str,
    api_key: str,
    region: str = "global",
    base_url: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Upload a WAV sample and create a reusable cloned voice."""
    if not api_key.strip():
        raise ValueError("MiniMax API key is not configured")
    normalized_voice_id = _validate_voice_id(voice_id)
    normalized_model = model.strip()
    if normalized_model not in MINIMAX_VOICE_CLONE_MODELS:
        raise ValueError(
            "MiniMax clone model must be one of: " + ", ".join(MINIMAX_VOICE_CLONE_MODELS)
        )

    api_base = resolve_minimax_base_url(region=region, base_url=base_url)
    headers = {"Authorization": f"Bearer {api_key.strip()}"}
    async with httpx.AsyncClient(headers=headers, timeout=60.0, transport=transport) as client:
        upload_response = await client.post(
            f"{api_base}/files/upload",
            data={"purpose": "voice_clone"},
            files={"file": ("voice-clone.wav", wav_bytes, "audio/wav")},
        )
        upload_payload = _parse_response(upload_response, "file upload")
        file_payload = upload_payload.get("file")
        file_id = file_payload.get("file_id") if isinstance(file_payload, dict) else None
        if not isinstance(file_id, (str, int)) or not str(file_id).strip():
            raise MiniMaxVoiceCloneError("MiniMax file upload did not return file.file_id")

        clone_response = await client.post(
            f"{api_base}/voice_clone",
            json={
                "file_id": int(file_id) if str(file_id).isdigit() else str(file_id),
                "voice_id": normalized_voice_id,
                "model": normalized_model,
            },
        )
        clone_payload = _parse_response(clone_response, "voice clone")
        returned_voice_id = clone_payload.get("voice_id")
        if isinstance(returned_voice_id, str) and returned_voice_id.strip():
            return returned_voice_id.strip()
        return normalized_voice_id
