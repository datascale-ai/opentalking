from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PostJson = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
Sleep = Callable[[float], Awaitable[None]]


def collect_wav2lip_preload_payloads(avatars_root: Path, *, enhanced: bool) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for manifest_path in sorted(Path(avatars_root).glob("*/manifest.json")):
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Skipping invalid avatar manifest during wav2lip preload: %s", manifest_path)
            continue
        metadata = raw.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if raw.get("model_type") != "wav2lip":
            continue
        if metadata.get("reference_mode") != "frames" or metadata.get("preprocessed") is not True:
            continue
        frame_dir = (manifest_path.parent / str(metadata.get("frame_dir") or "frames")).resolve()
        frame_metadata = metadata.get("frame_metadata")
        if not frame_metadata:
            log.warning("Skipping preprocessed wav2lip avatar without frame_metadata: %s", raw.get("id"))
            continue
        frame_metadata_path = (manifest_path.parent / str(frame_metadata)).resolve()
        if not frame_dir.is_dir() or not frame_metadata_path.is_file():
            log.warning("Skipping incomplete preprocessed wav2lip avatar: %s", raw.get("id"))
            continue
        payloads.append(
            {
                "avatar_id": str(raw.get("id") or manifest_path.parent.name),
                "ref_frame_dir": str(frame_dir),
                "ref_frame_metadata_path": str(frame_metadata_path),
                "width": int(raw.get("width") or 416),
                "height": int(raw.get("height") or 704),
                "fps": int(raw.get("fps") or 25),
                "preprocessed": True,
                "enable_enhanced_postprocessing": bool(enhanced),
            }
        )
    return payloads


async def _httpx_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"response": data}


async def preload_wav2lip_assets(
    avatars_root: Path,
    *,
    omnirt_endpoint: str,
    enhanced: bool,
    post_json: PostJson = _httpx_post_json,
    attempts: int = 6,
    retry_delay_seconds: float = 2.0,
    sleep: Sleep = asyncio.sleep,
) -> None:
    endpoint = omnirt_endpoint.strip().rstrip("/")
    if not endpoint:
        return
    url = f"{endpoint}/v1/avatar/wav2lip/preload"
    for payload in collect_wav2lip_preload_payloads(avatars_root, enhanced=enhanced):
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
                        "Wav2Lip avatar preload failed: avatar=%s attempts=%d",
                        avatar_id,
                        attempt,
                        exc_info=True,
                    )
                    break
                log.info(
                    "Wav2Lip avatar preload retry: avatar=%s attempt=%d/%d delay=%ss",
                    avatar_id,
                    attempt,
                    max_attempts,
                    retry_delay_seconds,
                    exc,
                )
                await sleep(max(0.0, float(retry_delay_seconds)))
        if result is None:
            continue
        log.info(
            "Wav2Lip avatar preload done: avatar=%s frames=%s cache_hit=%s elapsed_ms=%s",
            avatar_id,
            result.get("frames"),
            result.get("cache_hit"),
            result.get("elapsed_ms"),
        )
