"""百炼 CosyVoice：官方 ``dashscope.audio.tts_v2.SpeechSynthesizer``（WebSocket，实时二进制 PCM）。"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from opentalking.core.types.frames import AudioChunk

log = logging.getLogger(__name__)


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
            "CosyVoice WebSocket TTS 需要密钥：设置 DASHSCOPE_API_KEY 或 OPENTALKING_LLM_API_KEY。",
        )
    return api_key


def _pcm_format_for_sr(sample_rate: int) -> Any:
    from dashscope.audio.tts_v2 import AudioFormat

    sr = int(sample_rate)
    if sr <= 8000:
        return AudioFormat.PCM_8000HZ_MONO_16BIT
    if sr <= 16000:
        return AudioFormat.PCM_16000HZ_MONO_16BIT
    if sr <= 22050:
        return AudioFormat.PCM_22050HZ_MONO_16BIT
    return AudioFormat.PCM_24000HZ_MONO_16BIT


class DashScopeCosyVoiceWsAdapter:
    """CosyVoice：``tts_v2.SpeechSynthesizer`` WebSocket（非 HTTP/SSE）。"""

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
        self.default_voice = default_voice or "longanyang"
        self._model = (model.strip() if model and str(model).strip() else None) or "cosyvoice-v3-flash"

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return

        api_key = _ensure_api_key()
        try:
            import dashscope
            from dashscope.audio.tts_v2 import ResultCallback, SpeechSynthesizer
        except ImportError as e:
            raise RuntimeError(
                "dashscope package is required. Install: pip install 'dashscope>=1.25.11'",
            ) from e

        dashscope.api_key = api_key

        v = voice or self.default_voice
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        sentinel = object()
        done_exc: list[BaseException | None] = [None]

        pcm_fmt = _pcm_format_for_sr(self.sample_rate)
        eff_sr = int(pcm_fmt.sample_rate) if getattr(pcm_fmt, "sample_rate", 0) else int(self.sample_rate)
        ws_url_raw = os.environ.get("OPENTALKING_COSYVOICE_WS_URL", "").strip()
        ws_url = ws_url_raw if ws_url_raw else None

        class _Cb(ResultCallback):
            def on_data(self, data: bytes) -> None:
                if data:
                    try:
                        loop.call_soon_threadsafe(queue.put_nowait, bytes(data))
                    except Exception:  # noqa: BLE001
                        log.exception("CosyVoice WS audio queue push failed")

            def on_error(self, message: Any) -> None:
                done_exc[0] = RuntimeError(f"CosyVoice TTS error: {message}")

        def _run_ws() -> None:
            try:
                synth = SpeechSynthesizer(
                    model=self._model,
                    voice=v,
                    format=pcm_fmt,
                    callback=_Cb(),
                    url=ws_url,
                    additional_params={"enable_ssml": True},
                )
                synth.streaming_call(text)
                synth.streaming_complete(complete_timeout_millis=180000)
            except BaseException as exc:  # noqa: BLE001
                done_exc[0] = exc
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        await asyncio.get_running_loop().run_in_executor(None, _run_ws)

        pcm_acc = bytearray()
        bytes_per_chunk = max(2, int(eff_sr * (self.chunk_ms / 1000.0)) * 2)
        if bytes_per_chunk % 2:
            bytes_per_chunk += 1

        while True:
            item = await queue.get()
            if item is sentinel:
                break
            pcm_acc.extend(item)

            while len(pcm_acc) >= bytes_per_chunk:
                chunk_bytes = bytes(pcm_acc[:bytes_per_chunk])
                del pcm_acc[:bytes_per_chunk]
                arr = np.frombuffer(chunk_bytes, dtype=np.int16).copy()
                dur = 1000.0 * arr.size / eff_sr
                yield AudioChunk(
                    data=arr,
                    sample_rate=eff_sr,
                    duration_ms=float(dur),
                )

        if done_exc[0] is not None:
            raise done_exc[0]

        if pcm_acc:
            arr = np.frombuffer(bytes(pcm_acc), dtype=np.int16).copy()
            if arr.size % 2:
                arr = arr[: arr.size - (arr.size % 2)]
            if arr.size > 0:
                for c in _split_pcm_chunks(arr, eff_sr, self.chunk_ms):
                    yield c
