"""WebSocket client for OmniRT FasterLivePortrait video-clone streaming."""

from __future__ import annotations

import base64
import json
from typing import Any

try:
    import websockets
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    websockets = None  # type: ignore[assignment]

from opentalking.providers.synthesis.omnirt import (
    DEFAULT_VIDEO_CLONE_PATH_TEMPLATE,
    auth_headers,
    derive_video_clone_ws_url,
)

MAGIC_FRAME = b"FRAM"
MAGIC_VIDEO = b"VIDX"


class VideoCloneWSClient:
    """Small protocol client for source-avatar + driving-frame video cloning."""

    def __init__(
        self,
        ws_url: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if websockets is None:
            raise RuntimeError("websockets package required: pip install websockets")
        self._ws_url = ws_url
        self._extra_headers = dict(extra_headers or {})
        self._ws = None

    @staticmethod
    def resolve_url(settings: object, model: str = "fasterliveportrait") -> str:
        endpoint = str(getattr(settings, "omnirt_endpoint", "") or "").strip()
        if not endpoint:
            raise RuntimeError("OMNIRT_ENDPOINT is required for video clone.")
        template = (
            str(getattr(settings, "omnirt_video_clone_path_template", "") or "").strip()
            or DEFAULT_VIDEO_CLONE_PATH_TEMPLATE
        )
        return derive_video_clone_ws_url(endpoint, model, path_template=template)

    @staticmethod
    def from_settings(settings: object, model: str = "fasterliveportrait") -> "VideoCloneWSClient":
        return VideoCloneWSClient(
            VideoCloneWSClient.resolve_url(settings, model),
            extra_headers=auth_headers(settings),
        )

    @staticmethod
    def frame_payload(frame_bytes: bytes) -> bytes:
        return MAGIC_FRAME + frame_bytes

    async def connect(self) -> None:
        kwargs: dict[str, Any] = {"max_size": 50 * 1024 * 1024, "open_timeout": 30, "close_timeout": 10}
        if self._extra_headers:
            try:
                self._ws = await ws_connect(self._ws_url, additional_headers=self._extra_headers, **kwargs)
            except TypeError:
                self._ws = await ws_connect(self._ws_url, extra_headers=self._extra_headers, **kwargs)
        else:
            self._ws = await ws_connect(self._ws_url, **kwargs)

    async def init_session(
        self,
        *,
        ref_image: bytes,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._ws is None:
            await self.connect()
        payload: dict[str, Any] = {
            "type": "init",
            "ref_image": base64.b64encode(ref_image).decode("ascii"),
        }
        payload.update(dict(config or {}))
        await self._ws.send(json.dumps(payload, ensure_ascii=False))
        response = await self._ws.recv()
        if not isinstance(response, str):
            raise RuntimeError("video-clone init returned a binary response")
        message = json.loads(response)
        if message.get("type") == "error":
            raise RuntimeError(f"video-clone init failed: {message.get('message')}")
        return message

    async def send_frame(self, frame_bytes: bytes) -> bytes:
        if self._ws is None:
            raise RuntimeError("Not connected. Call connect() first.")
        await self._ws.send(self.frame_payload(frame_bytes))
        response = await self._ws.recv()
        if isinstance(response, str):
            message = json.loads(response)
            raise RuntimeError(f"video-clone frame failed: {message.get('message')}")
        if len(response) < 8 or response[:4] != MAGIC_VIDEO:
            raise RuntimeError(f"Unexpected video-clone response: magic={response[:4]!r}, len={len(response)}")
        return bytes(response)

    async def send_config_update(self, config: dict[str, Any]) -> dict[str, Any]:
        if self._ws is None:
            await self.connect()
        await self._ws.send(json.dumps({"type": "config_update", "config": config}, ensure_ascii=False))
        response = await self._ws.recv()
        if not isinstance(response, str):
            raise RuntimeError("video-clone config update returned a binary response")
        message = json.loads(response)
        if message.get("type") == "error":
            raise RuntimeError(f"video-clone config update failed: {message.get('message')}")
        return message

    async def close(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "close"}))
            await self._ws.recv()
        except Exception:
            pass
        try:
            await self._ws.close()
        finally:
            self._ws = None
