"""千问实时语音合成（DashScope WebSocket），兼容 EdgeTTSAdapter 流式接口。"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.qwen_tts_voices import QWEN_CANTONESE_VOICES, normalize_optional_qwen_voice

log = logging.getLogger(__name__)

# ``PCM_24000HZ_MONO_16BIT`` 会话仅接受 ``sample_rate=24000``；下游 FlashTalk 仍常用 16k。
_QWEN_REALTIME_WIRE_SR = 24000


def _resample_mono_i16_linear(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Mono int16 线性重采样（避免整仓依赖 librosa）。"""
    pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
    if pcm.size == 0 or src_sr == dst_sr:
        return pcm.copy()
    pcm_f = pcm.astype(np.float32) * (1.0 / 32768.0)
    ratio = dst_sr / src_sr
    n_dst = max(1, int(round(pcm.size * ratio)))
    xi = np.linspace(0.0, pcm.size - 1.0, num=n_dst)
    i0 = np.floor(xi).astype(np.int64)
    i0 = np.clip(i0, 0, pcm.size - 1)
    i1 = np.clip(i0 + 1, 0, pcm.size - 1)
    t = xi - np.floor(xi).astype(np.float64)
    out_f = pcm_f[i0] * (1.0 - t) + pcm_f[i1] * t
    return np.clip(np.round(out_f * 32768.0), -32768, 32767).astype(np.int16)


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return default if raw is None or not str(raw).strip() else str(raw).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _settings_value(name: str, default: str = "") -> str:
    try:
        from opentalking.core.config import get_settings

        value = getattr(get_settings(), name, default)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return default


def _qwen_language_type() -> str:
    raw = _env_str("OPENTALKING_QWEN_TTS_LANGUAGE", "Chinese")
    if raw.lower() in {"cantonese", "yue", "粤语", "廣東話", "广东话"}:
        return "Chinese"
    return raw


def _qwen_cantonese_voice_override() -> str | None:
    dialect = os.environ.get("OPENTALKING_QWEN_TTS_DIALECT", "").strip().lower()
    language = os.environ.get("OPENTALKING_QWEN_TTS_LANGUAGE", "").strip().lower()
    if dialect not in {"cantonese", "yue", "粤语", "廣東話", "广东话"} and language not in {
        "cantonese",
        "yue",
        "粤语",
        "廣東話",
        "广东话",
    }:
        return None
    return normalize_optional_qwen_voice(os.environ.get("OPENTALKING_QWEN_TTS_CANTONESE_VOICE")) or "Kiki"


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


def _close_client_sync(client: Any) -> None:
    try:
        client.finish()
    except Exception:  # noqa: BLE001
        pass
    try:
        client.close()
    except Exception:  # noqa: BLE001
        pass


async def _run_blocking(fn: Any, *args: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


class DashScopeQwenTTSAdapter:
    """百炼 Qwen-TTS-Realtime（WebSocket），流式输出 PCM。

    当 ``OPENTALKING_QWEN_TTS_REUSE_WS`` 为真（默认）时，在同一次 ``speak`` 中
    多次调用 ``synthesize_stream`` 会复用同一条 WebSocket，仅在显式 ``aclose()``
    或退出一轮单句模式（``REUSE_WS=0``）时关闭连接。
    """

    def __init__(
        self,
        default_voice: str | None = None,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        *,
        model: str | None = None,
        service_url: str | None = None,
        reuse_ws: bool | None = None,
    ) -> None:
        # 对外输出采样率（与 FlashTalk / 会话配置一致，默认 16k）
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        # 与 ``AudioFormat.PCM_24000HZ_MONO_16BIT`` 及 DashScope ``update_session`` 要求一致
        self._wire_sr = _QWEN_REALTIME_WIRE_SR
        self.default_voice = normalize_optional_qwen_voice(default_voice) or normalize_optional_qwen_voice(
            _env_str(
                "OPENTALKING_TTS_DASHSCOPE_VOICE",
                _settings_value("tts_dashscope_voice", "Cherry"),
            ),
        ) or "Cherry"
        self._model = (model.strip() if model and str(model).strip() else None) or _env_str(
            "OPENTALKING_TTS_DASHSCOPE_MODEL",
            _settings_value("tts_dashscope_model", "qwen3-tts-flash-realtime"),
        )
        self._ws_url = (service_url.strip() if service_url and str(service_url).strip() else None) or _env_str(
            "OPENTALKING_TTS_DASHSCOPE_SERVICE_URL",
            _settings_value("tts_dashscope_service_url", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"),
        )
        self._mode = _env_str("OPENTALKING_QWEN_TTS_MODE", "commit")
        self._reuse_ws = _env_bool("OPENTALKING_QWEN_TTS_REUSE_WS", True) if reuse_ws is None else reuse_ws

        # Persistent connection (reuse mode)
        self._client: Any | None = None
        self._session_voice: str | None = None
        self._stable_cb: Any | None = None
        self._active_inbox: asyncio.Queue[Any] | None = None
        self._session_ready = threading.Event()

    async def aclose(self) -> None:
        """关闭复用的 WebSocket（在单次 speak / 单次整段朗读结束后务必调用）。"""
        self._active_inbox = None
        client = self._client
        self._client = None
        self._session_voice = None
        self._stable_cb = None
        if client is not None:
            await _run_blocking(_close_client_sync, client)

    def _ensure_api_key(self) -> str:
        api_key = os.environ.get("OPENTALKING_TTS_DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            try:
                from opentalking.core.config import get_settings

                api_key = getattr(get_settings(), "tts_dashscope_api_key", "").strip()
            except Exception:
                pass
        if not api_key:
            raise RuntimeError(
                "DashScope Qwen TTS 需要密钥：请设置 OPENTALKING_TTS_DASHSCOPE_API_KEY。",
            )
        return api_key

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        v = normalize_optional_qwen_voice(voice) or self.default_voice
        cantonese_voice = _qwen_cantonese_voice_override()
        if cantonese_voice is not None and v not in QWEN_CANTONESE_VOICES:
            log.info("Qwen TTS Cantonese mode overriding voice %r -> %r", v, cantonese_voice)
            v = cantonese_voice
        api_key = self._ensure_api_key()

        try:
            import dashscope
            from dashscope.audio.qwen_tts_realtime import (
                AudioFormat,
                QwenTtsRealtime,
                QwenTtsRealtimeCallback,
            )
        except ImportError as e:
            raise RuntimeError(
                "dashscope package is required. Install: pip install 'dashscope>=1.25.11'",
            ) from e

        dashscope.api_key = api_key
        loop = asyncio.get_running_loop()
        inbox: asyncio.Queue[Any] = asyncio.Queue()
        self._active_inbox = inbox

        if not self._reuse_ws:
            async for chunk in self._synthesize_one_shot_impl(
                loop=loop,
                inbox=inbox,
                v=v,
                text=text,
                AudioFormat=AudioFormat,
                QwenTtsRealtime=QwenTtsRealtime,
                QwenTtsRealtimeCallback=QwenTtsRealtimeCallback,
            ):
                yield chunk
            return

        def _prepare_and_send() -> None:
            if self._client is None:
                class _StableCb(QwenTtsRealtimeCallback):
                    def __init__(self, adapter: DashScopeQwenTTSAdapter) -> None:
                        self._adapter = adapter

                    def on_event(self, message: Any) -> None:
                        if not isinstance(message, dict):
                            return
                        if message.get("type") == "session.updated":
                            self._adapter._session_ready.set()
                        q = self._adapter._active_inbox
                        if q is None:
                            return
                        try:
                            loop.call_soon_threadsafe(q.put_nowait, message)
                        except Exception:  # noqa: BLE001
                            log.exception("DashScope TTS inbox push failed")

                    def on_close(self, close_status_code: Any = None, close_msg: Any = None) -> None:
                        _ = close_status_code
                        _ = close_msg

                cb = _StableCb(self)
                self._stable_cb = cb
                client = QwenTtsRealtime(model=self._model, callback=cb, url=self._ws_url)
                client.connect()
                self._session_ready.clear()
                client.update_session(
                    voice=v,
                    response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                    mode=self._mode,
                    sample_rate=self._wire_sr,
                    language_type=_qwen_language_type(),
                )
                self._session_voice = v
                self._client = client
                if not self._session_ready.wait(timeout=5.0):
                    raise TimeoutError("DashScope TTS session update timed out")
            elif v != self._session_voice:
                assert self._client is not None
                self._session_ready.clear()
                self._client.update_session(
                    voice=v,
                    response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                    mode=self._mode,
                    sample_rate=self._wire_sr,
                    language_type=_qwen_language_type(),
                )
                self._session_voice = v
                if not self._session_ready.wait(timeout=5.0):
                    raise TimeoutError("DashScope TTS session update timed out")

            assert self._client is not None
            self._client.append_text(text)
            if self._mode == "commit":
                self._client.commit()
            else:
                self._client.finish()

        await _run_blocking(_prepare_and_send)

        async for chunk in self._drain_response_pcm(inbox):
            yield chunk

    async def _synthesize_one_shot_impl(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        inbox: asyncio.Queue[Any],
        v: str,
        text: str,
        AudioFormat: Any,
        QwenTtsRealtime: Any,
        QwenTtsRealtimeCallback: Any,
    ):
        """不复用 WS：一轮 connect → 合成 → close（兼容旧行为 / 调试）。"""
        client_holder: dict[str, Any] = {}

        session_ready = threading.Event()

        class _Cb(QwenTtsRealtimeCallback):
            def on_event(self, message: Any) -> None:
                if not isinstance(message, dict):
                    return
                if message.get("type") == "session.updated":
                    session_ready.set()
                try:
                    loop.call_soon_threadsafe(inbox.put_nowait, message)
                except Exception:  # noqa: BLE001
                    log.exception("DashScope TTS inbox push failed")

            def on_close(self, close_status_code: Any = None, close_msg: Any = None) -> None:
                _ = close_status_code
                _ = close_msg

        def _run_one_roundtrip() -> None:
            cb = _Cb()
            client = QwenTtsRealtime(model=self._model, callback=cb, url=self._ws_url)
            client.connect()
            client.update_session(
                voice=v,
                response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                mode=self._mode,
                sample_rate=self._wire_sr,
                language_type=_qwen_language_type(),
            )
            client_holder["c"] = client
            if not session_ready.wait(timeout=5.0):
                raise TimeoutError("DashScope TTS session update timed out")
            client.append_text(text)
            if self._mode == "commit":
                client.commit()
            else:
                client.finish()

        await _run_blocking(_run_one_roundtrip)
        client = client_holder.get("c")

        try:
            async for chunk in self._drain_response_pcm(inbox):
                yield chunk
        finally:
            if client is not None:
                await _run_blocking(_close_client_sync, client)

    async def _drain_response_pcm(
        self,
        inbox: asyncio.Queue[Any],
    ) -> AsyncIterator[AudioChunk]:
        pcm_acc = bytearray()
        wire_sr = self._wire_sr
        bytes_per_chunk = max(2, int(wire_sr * (self.chunk_ms / 1000.0)) * 2)
        if bytes_per_chunk % 2:
            bytes_per_chunk += 1

        completed = False
        try:
            while True:
                msg = await asyncio.wait_for(inbox.get(), timeout=180.0)
                mtype = msg.get("type")
                if mtype == "response.audio.delta":
                    raw = base64.b64decode(msg["delta"])
                    pcm_acc.extend(raw)
                    while len(pcm_acc) >= bytes_per_chunk:
                        chunk_bytes = bytes(pcm_acc[:bytes_per_chunk])
                        del pcm_acc[:bytes_per_chunk]
                        arr_w = np.frombuffer(chunk_bytes, dtype=np.int16).copy()
                        arr = (
                            _resample_mono_i16_linear(arr_w, wire_sr, self.sample_rate)
                            if wire_sr != self.sample_rate
                            else arr_w
                        )
                        dur = 1000.0 * arr.size / self.sample_rate
                        yield AudioChunk(
                            data=arr,
                            sample_rate=self.sample_rate,
                            duration_ms=float(dur),
                        )
                elif mtype in ("response.done", "session.finished"):
                    completed = True
                    break
                elif mtype == "error" or "error" in msg:
                    raise RuntimeError(f"DashScope TTS error: {msg}")
        finally:
            self._active_inbox = None
            if self._reuse_ws and self._client is not None and not completed:

                def _finish_in_flight() -> None:
                    try:
                        self._client.finish()
                    except Exception:  # noqa: BLE001
                        pass

                await _run_blocking(_finish_in_flight)

        if pcm_acc:
            arr_w = np.frombuffer(bytes(pcm_acc), dtype=np.int16).copy()
            if arr_w.size % 2:
                arr_w = arr_w[: arr_w.size - (arr_w.size % 2)]
            if arr_w.size > 0:
                arr = (
                    _resample_mono_i16_linear(arr_w, wire_sr, self.sample_rate)
                    if wire_sr != self.sample_rate
                    else arr_w
                )
                for c in _split_pcm_chunks(arr, self.sample_rate, self.chunk_ms):
                    yield c
