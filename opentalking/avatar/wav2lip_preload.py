from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from opentalking.avatar.wav2lip_config import (
    manifest_preferred_wav2lip_postprocess_mode,
    normalize_wav2lip_postprocess_mode,
)

log = logging.getLogger(__name__)

PostJson = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
Sleep = Callable[[float], Awaitable[None]]


def _payload_from_manifest_path(
    manifest_path: Path,
    *,
    default_postprocess_mode: str,
) -> dict[str, Any] | None:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Skipping invalid avatar manifest during wav2lip preload: %s", manifest_path)
        return None
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        return None
    if raw.get("model_type") != "wav2lip":
        return None
    if metadata.get("reference_mode") != "frames" or metadata.get("preprocessed") is not True:
        return None
    frame_dir = (manifest_path.parent / str(metadata.get("frame_dir") or "frames")).resolve()
    frame_metadata = metadata.get("frame_metadata")
    avatar_id = str(raw.get("id") or manifest_path.parent.name)
    if not frame_metadata:
        log.warning("Skipping preprocessed wav2lip avatar without frame_metadata: %s", avatar_id)
        return None
    frame_metadata_path = (manifest_path.parent / str(frame_metadata)).resolve()
    prepared_cache_dir = (manifest_path.parent / "wav2lip").resolve()
    if not frame_dir.is_dir() or not frame_metadata_path.is_file():
        log.warning("Skipping incomplete preprocessed wav2lip avatar: %s", avatar_id)
        return None
    return {
        "avatar_id": avatar_id,
        "ref_frame_dir": str(frame_dir),
        "ref_frame_metadata_path": str(frame_metadata_path),
        "prepared_cache_dir": str(prepared_cache_dir),
        "width": int(raw.get("width") or 416),
        "height": int(raw.get("height") or 704),
        "fps": int(raw.get("fps") or 25),
        "preprocessed": True,
        "wav2lip_postprocess_mode": manifest_preferred_wav2lip_postprocess_mode(
            raw,
            default=default_postprocess_mode,
        ),
    }


def collect_wav2lip_preload_payloads(avatars_root: Path, *, postprocess_mode: str) -> list[dict[str, Any]]:
    default_postprocess_mode = normalize_wav2lip_postprocess_mode(postprocess_mode)
    payloads: list[dict[str, Any]] = []
    for manifest_path in sorted(Path(avatars_root).glob("*/manifest.json")):
        payload = _payload_from_manifest_path(
            manifest_path,
            default_postprocess_mode=default_postprocess_mode,
        )
        if payload is not None:
            payloads.append(payload)
    return payloads


def filter_wav2lip_preload_payloads(
    payloads: list[dict[str, Any]],
    *,
    exclude_avatar_ids: set[str],
) -> list[dict[str, Any]]:
    excluded = {str(item).strip() for item in exclude_avatar_ids if str(item).strip()}
    return [
        payload
        for payload in payloads
        if str(payload.get("avatar_id") or "").strip() not in excluded
    ]


def collect_wav2lip_preload_payload_for_avatar(
    avatars_root: Path,
    avatar_id: str,
    *,
    postprocess_mode: str,
) -> dict[str, Any] | None:
    avatar_id = str(avatar_id).strip()
    if not avatar_id:
        return None
    avatars_root = Path(avatars_root).resolve()
    manifest_path = (avatars_root / avatar_id / "manifest.json").resolve()
    try:
        manifest_path.relative_to(avatars_root)
    except ValueError:
        return None
    if not manifest_path.is_file():
        return None
    return _payload_from_manifest_path(
        manifest_path,
        default_postprocess_mode=normalize_wav2lip_postprocess_mode(postprocess_mode),
    )


async def _httpx_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    import httpx

    timeout = httpx.Timeout(180.0, connect=3.0, read=180.0, write=10.0, pool=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"response": data}


async def preload_wav2lip_payloads(
    payloads: list[dict[str, Any]],
    *,
    omnirt_endpoint: str,
    post_json: PostJson = _httpx_post_json,
    attempts: int = 6,
    retry_delay_seconds: float = 2.0,
    sleep: Sleep = asyncio.sleep,
) -> None:
    endpoint = omnirt_endpoint.strip().rstrip("/")
    if not endpoint:
        return
    url = f"{endpoint}/v1/audio2video/wav2lip/preload"
    for payload in payloads:
        avatar_id = payload.get("avatar_id")
        result: dict[str, Any] | None = None
        max_attempts = max(1, int(attempts))
        for attempt in range(1, max_attempts + 1):
            try:
                result = await post_json(url, payload)
                break
            except Exception as exc:
                if attempt >= max_attempts:
                    log.warning(
                        "Wav2Lip avatar preload failed: avatar=%s attempts=%d error=%s: %s",
                        avatar_id,
                        attempt,
                        type(exc).__name__,
                        exc,
                    )
                    break
                log.info(
                    "Wav2Lip avatar preload retry: avatar=%s attempt=%d/%d delay=%ss error=%s: %s",
                    avatar_id,
                    attempt,
                    max_attempts,
                    retry_delay_seconds,
                    type(exc).__name__,
                    exc,
                )
                await sleep(max(0.0, float(retry_delay_seconds)))
        if result is None:
            continue
        log.info(
            "Wav2Lip avatar preload done: avatar=%s frames=%s cache_hit=%s cache_source=%s elapsed_ms=%s",
            avatar_id,
            result.get("frames"),
            result.get("cache_hit"),
            result.get("cache_source"),
            result.get("elapsed_ms"),
        )


async def preload_wav2lip_assets(
    avatars_root: Path,
    *,
    omnirt_endpoint: str,
    postprocess_mode: str,
    post_json: PostJson = _httpx_post_json,
    attempts: int = 6,
    retry_delay_seconds: float = 2.0,
    sleep: Sleep = asyncio.sleep,
) -> None:
    await preload_wav2lip_payloads(
        collect_wav2lip_preload_payloads(avatars_root, postprocess_mode=postprocess_mode),
        omnirt_endpoint=omnirt_endpoint,
        post_json=post_json,
        attempts=attempts,
        retry_delay_seconds=retry_delay_seconds,
        sleep=sleep,
    )


async def preload_wav2lip_avatar(
    avatars_root: Path,
    avatar_id: str,
    *,
    omnirt_endpoint: str,
    postprocess_mode: str,
    post_json: PostJson = _httpx_post_json,
    attempts: int = 1,
    retry_delay_seconds: float = 0.5,
    sleep: Sleep = asyncio.sleep,
) -> None:
    payload = collect_wav2lip_preload_payload_for_avatar(
        avatars_root,
        avatar_id,
        postprocess_mode=postprocess_mode,
    )
    if payload is None:
        return
    await preload_wav2lip_payloads(
        [payload],
        omnirt_endpoint=omnirt_endpoint,
        post_json=post_json,
        attempts=attempts,
        retry_delay_seconds=retry_delay_seconds,
        sleep=sleep,
    )
