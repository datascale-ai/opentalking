"""百炼 Sambert：``dashscope.audio.tts.SpeechSynthesizer``（``api_protocol=WebSocket`` 流式 PCM）。"""

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
            "百炼 Sambert TTS 需要密钥：设置 DASHSCOPE_API_KEY 或 OPENTALKING_LLM_API_KEY。",
        )
    return api_key


class DashScopeSambertTTSAdapter:
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
        self.default_voice = default_voice or "zhichu"
        self._model = (model.strip() if model and str(model).strip() else None) or "sambert-zhichu-v1"

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        _ = voice or self.default_voice  # legacy API uses model voice only; reserved for future
        api_key = _ensure_api_key()

        try:
            import dashscope
            from dashscope.audio.tts import ResultCallback, SpeechSynthesizer, SpeechSynthesisResult
        except ImportError as e:
            raise RuntimeError(
                "dashscope package is required. Install: pip install 'dashscope>=1.25.11'",
            ) from e

        dashscope.api_key = api_key

        loop = asyncio.get_running_loop()
        chunk_q: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        done_exc: list[BaseException | None] = [None]

        class _Cb(ResultCallback):
            def on_event(self, result: SpeechSynthesisResult) -> None:
                raw = result.get_audio_frame()
                if raw:
                    try:
                        loop.call_soon_threadsafe(chunk_q.put_nowait, bytes(raw))
                    except Exception:  # noqa: BLE001
                        log.exception("Sambert chunk queue push failed")

            def on_error(self, response: Any) -> None:
                done_exc[0] = RuntimeError(f"Sambert TTS error: {response}")
                loop.call_soon_threadsafe(chunk_q.put_nowait, None)

            def on_complete(self) -> None:
                loop.call_soon_threadsafe(chunk_q.put_nowait, None)

            def on_close(self) -> None:
                pass

        def _run_call() -> None:
            try:
                SpeechSynthesizer.call(
                    model=self._model,
                    text=text,
                    callback=_Cb(),
                    format="pcm",
                    sample_rate=self.sample_rate,
                )
            except BaseException as exc:  # noqa: BLE001
                done_exc[0] = exc
                loop.call_soon_threadsafe(chunk_q.put_nowait, None)

        await asyncio.get_running_loop().run_in_executor(None, _run_call)

        pcm_acc = bytearray()
        bytes_per_chunk = max(2, int(self.sample_rate * (self.chunk_ms / 1000.0)) * 2)
        if bytes_per_chunk % 2:
            bytes_per_chunk += 1

        while True:
            raw = await chunk_q.get()
            if raw is None:
                break
            pcm_acc.extend(raw)
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

        if done_exc[0] is not None:
            raise done_exc[0]

        if pcm_acc:
            arr = np.frombuffer(bytes(pcm_acc), dtype=np.int16).copy()
            if arr.size % 2:
                arr = arr[: arr.size - (arr.size % 2)]
            if arr.size > 0:
                for c in _split_pcm_chunks(arr, self.sample_rate, self.chunk_ms):
                    yield c
