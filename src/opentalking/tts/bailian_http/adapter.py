"""百炼 MiniMax：仅支持 ``multimodal-generation/generation``（HTTP/SSE）。

MiniMax 官方文档为该 REST 路径；DashScope SDK 暂无专用 WebSocket，故此处保留 HTTP 流式。
CosyVoice 请使用 ``cosyvoice_ws`` 适配器（WebSocket）。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Any

import numpy as np

from opentalking.core.types.frames import AudioChunk

log = logging.getLogger(__name__)


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return default if raw is None or not str(raw).strip() else str(raw).strip()


def _split_pcm_chunks(pcm: np.ndarray, sr: int, chunk_ms: float) -> list[AudioChunk]:
    samples_per_chunk = max(1, int(sr * (chunk_ms / 1000.0)))
    out: list[AudioChunk] = []
    for i in range(0, len(pcm), samples_per_chunk):
        part = pcm[i : i + samples_per_chunk]
        if part.size == 0:
            continue
        dur = 1000.0 * part.size / sr
        out.append(
            AudioChunk(
                data=part.astype(np.int16),
                sample_rate=sr,
                duration_ms=float(dur),
            )
        )
    return out


def _ensure_api_key() -> str:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        try:
            from opentalking.core.config import get_settings

            api_key = (get_settings().llm_api_key or "").strip()
        except Exception:
            pass
    if not api_key:
        raise RuntimeError(
            "MiniMax TTS 需要密钥：设置 DASHSCOPE_API_KEY 或 OPENTALKING_LLM_API_KEY。",
        )
    return api_key


def _pcm_from_multimodal_chunk(rsp: Any) -> bytes | None:
    if rsp.status_code != HTTPStatus.OK:
        return None
    out = rsp.output
    if out is None:
        return None
    audio: Any = None
    if isinstance(out, dict):
        audio = out.get("audio")
    else:
        audio = getattr(out, "audio", None)
    if audio is None:
        return None
    if isinstance(audio, dict):
        b64 = audio.get("data")
        if not b64:
            return None
        return base64.b64decode(b64)
    data = getattr(audio, "data", None)
    if not data:
        return None
    return base64.b64decode(data)


def _multimodal_stream_error_message(rsp: Any) -> str | None:
    if rsp.status_code == HTTPStatus.OK:
        return None
    msg = getattr(rsp, "message", None) or ""
    code = getattr(rsp, "code", None)
    parts = [p for p in (code, msg) if p]
    return " ".join(str(p) for p in parts) if parts else f"HTTP {rsp.status_code}"


class DashScopeMinimaxMultimodalAdapter:
    """MiniMax：``BaseApi`` → ``aigc/multimodal-generation/generation``（SSE）。"""

    def __init__(
        self,
        default_voice: str | None = None,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        *,
        model: str | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.default_voice = default_voice or "male-qn-qingse"
        self._model = (model.strip() if model and str(model).strip() else None) or "MiniMax/speech-02-turbo"

    def _voice_id(self, voice: str | None) -> str:
        v = (voice or "").strip()
        if v:
            return v
        return _env_str("OPENTALKING_MINIMAX_VOICE_ID", "male-qn-qingse")

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return

        api_key = _ensure_api_key()
        voice_id = self._voice_id(voice)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        sentinel = object()

        input_payload: dict[str, Any] = {
            "text": text,
            "voice_setting": {"voice_id": voice_id},
            "audio_setting": {
                "format": "pcm",
                "sample_rate": int(self.sample_rate),
                "channel": 1,
            },
        }

        def _worker() -> None:
            import dashscope
            from dashscope.client.base_api import BaseApi

            dashscope.api_key = api_key
            try:
                gen = BaseApi.call(
                    model=self._model,
                    input=input_payload,
                    task_group="aigc",
                    task="multimodal-generation",
                    function="generation",
                    api_key=api_key,
                    stream=True,
                )
                for rsp in gen:
                    err = _multimodal_stream_error_message(rsp)
                    if err:
                        raise RuntimeError(err)
                    pcm = _pcm_from_multimodal_chunk(rsp)
                    if pcm:
                        loop.call_soon_threadsafe(queue.put_nowait, pcm)
            except BaseException as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        await asyncio.get_running_loop().run_in_executor(None, _worker)

        pcm_acc = bytearray()
        bytes_per_chunk = max(2, int(self.sample_rate * (self.chunk_ms / 1000.0)) * 2)
        if bytes_per_chunk % 2:
            bytes_per_chunk += 1

        while True:
            item = await queue.get()
            if isinstance(item, BaseException):
                raise item
            if item is sentinel:
                break
            pcm_acc.extend(item)
            while len(pcm_acc) >= bytes_per_chunk:
                chunk_bytes = bytes(pcm_acc[:bytes_per_chunk])
                del pcm_acc[:bytes_per_chunk]
                arr = np.frombuffer(chunk_bytes, dtype=np.int16).copy()
                dur = 1000.0 * arr.size / self.sample_rate
                yield AudioChunk(
                    data=arr,
                    sample_rate=self.sample_rate,
                    duration_ms=float(dur),
                )

        if pcm_acc:
            arr = np.frombuffer(bytes(pcm_acc), dtype=np.int16).copy()
            if arr.size % 2:
                arr = arr[: arr.size - (arr.size % 2)]
            if arr.size > 0:
                for c in _split_pcm_chunks(arr, self.sample_rate, self.chunk_ms):
                    yield c


# 兼容旧名称（仅 MiniMax）
DashScopeHttpTTSAdapter = DashScopeMinimaxMultimodalAdapter
