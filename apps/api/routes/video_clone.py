from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from opentalking.providers.synthesis.availability import _fetch_omnirt_audio2video_models
from opentalking.providers.synthesis.video_clone.ws_client import VideoCloneWSClient

router = APIRouter(prefix="/video-clone", tags=["video-clone"])


def _error(code: str, message: str) -> dict[str, str]:
    return {"type": "error", "code": code, "message": message}


def _resolve_avatar_dir(avatars_root: Path, avatar_id: str) -> Path:
    avatar_dir = (avatars_root / avatar_id).resolve()
    try:
        avatar_dir.relative_to(avatars_root.resolve())
    except ValueError as exc:
        raise ValueError("invalid avatar_id") from exc
    if not avatar_dir.is_dir():
        raise FileNotFoundError("avatar not found")
    return avatar_dir


def _read_manifest(avatar_dir: Path) -> dict[str, Any]:
    manifest_path = avatar_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _avatar_source_image_path(avatar_dir: Path, manifest: dict[str, Any]) -> Path | None:
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    candidates: list[str] = []
    for key in ("source_image", "source_image_path", "reference_image"):
        value = metadata.get(key)
        if value:
            candidates.append(str(value))
    candidates.extend(("reference.png", "reference.jpg", "reference.jpeg", "reference.webp", "preview.png"))
    root = avatar_dir.resolve()
    for raw in candidates:
        candidate = (root / raw).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def collect_avatar_source_payload(avatars_root: Path, avatar_id: str) -> dict[str, Any]:
    avatar_dir = _resolve_avatar_dir(avatars_root, avatar_id)
    manifest = _read_manifest(avatar_dir)
    source_path = _avatar_source_image_path(avatar_dir, manifest)
    if source_path is None:
        raise FileNotFoundError("avatar source image not found")
    return {
        "avatar_id": avatar_id,
        "ref_image": base64.b64encode(source_path.read_bytes()).decode("ascii"),
        "width": int(manifest.get("width") or 416),
        "height": int(manifest.get("height") or 704),
        "fps": int(manifest.get("fps") or 25),
    }


async def _connect_video_clone_client(settings: object) -> VideoCloneWSClient:
    client = VideoCloneWSClient.from_settings(settings)
    await client.connect()
    return client


@router.get("/status")
async def video_clone_status(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    models = await _fetch_omnirt_audio2video_models(settings)
    connected = "fasterliveportrait_video_clone" in models or "fasterliveportrait" in models
    return {
        "model": "fasterliveportrait",
        "connected": connected,
        "reason": "omnirt" if connected else "omnirt_unavailable",
    }


@router.websocket("/fasterliveportrait/ws")
async def fasterliveportrait_video_clone_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = websocket.app.state.settings
    avatars_root = Path(getattr(settings, "avatars_dir")).resolve()
    upstream: VideoCloneWSClient | None = None
    upstream_to_client: asyncio.Task[None] | None = None

    async def forward_upstream() -> None:
        assert upstream is not None
        ws = upstream._ws
        if ws is None:
            return
        async for message in ws:
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("text") is not None:
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    await websocket.send_json(_error("bad_json", "Invalid JSON"))
                    continue
                msg_type = payload.get("type")
                if msg_type == "init":
                    avatar_id = str(payload.get("avatar_id") or "").strip()
                    if not avatar_id:
                        await websocket.send_json(_error("missing_avatar", "avatar_id is required"))
                        continue
                    try:
                        source = collect_avatar_source_payload(avatars_root, avatar_id)
                    except FileNotFoundError:
                        await websocket.send_json(_error("avatar_not_found", "avatar not found"))
                        continue
                    except ValueError as exc:
                        await websocket.send_json(_error("invalid_avatar", str(exc)))
                        continue
                    try:
                        upstream = await _connect_video_clone_client(settings)
                        config = {key: value for key, value in payload.items() if key not in {"type", "avatar_id"}}
                        config.setdefault("width", source["width"])
                        config.setdefault("height", source["height"])
                        config.setdefault("fps", source["fps"])
                        await upstream.init_session(
                            ref_image=base64.b64decode(source["ref_image"]),
                            config=config,
                        )
                    except Exception as exc:  # noqa: BLE001
                        if upstream is not None:
                            await upstream.close()
                            upstream = None
                        await websocket.send_json(_error("upstream_unavailable", str(exc)))
                        continue
                    upstream_to_client = asyncio.create_task(forward_upstream())
                    await websocket.send_json(
                        {
                            "type": "init_ok",
                            "model": "fasterliveportrait",
                            "avatar_id": avatar_id,
                            "width": int(config.get("width") or source["width"]),
                            "height": int(config.get("height") or source["height"]),
                            "fps": int(config.get("fps") or source["fps"]),
                        }
                    )
                elif msg_type == "close":
                    if upstream_to_client is not None:
                        upstream_to_client.cancel()
                        upstream_to_client = None
                    if upstream is not None:
                        await upstream.close()
                        upstream = None
                    await websocket.send_json({"type": "close_ok"})
                elif msg_type == "config_update":
                    if upstream is None or upstream._ws is None:
                        await websocket.send_json(_error("session_required", "Send init before config_update"))
                        continue
                    await upstream._ws.send(json.dumps(payload, ensure_ascii=False))
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                else:
                    await websocket.send_json(_error("unsupported_message", f"Unsupported message: {msg_type}"))
            elif message.get("bytes") is not None:
                if upstream is None or upstream._ws is None:
                    await websocket.send_json(_error("session_required", "Send init before frames"))
                    continue
                await upstream._ws.send(message["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        if upstream_to_client is not None:
            upstream_to_client.cancel()
        if upstream is not None:
            await upstream.close()
