from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
from typing import AsyncIterator

import edge_tts
import numpy as np

try:
    import av
except ImportError:
    av = None  # type: ignore[assignment]

from opentalking.core.types.frames import AudioChunk

log = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _ffmpeg_bin() -> str:
    return os.environ.get("OPENTALKING_FFMPEG_BIN", "").strip() or "ffmpeg"


def _decode_mp3_to_pcm16_mono(mp3_bytes: bytes, target_sr: int) -> tuple[np.ndarray, int]:
    if av is None:
        raise RuntimeError("Decoding TTS audio requires PyAV (av package).")
    buf = io.BytesIO(mp3_bytes)
    container = av.open(buf, format="mp3")
    pcm_chunks: list[np.ndarray] = []
    in_sr = target_sr
    for frame in container.decode(audio=0):
        arr = frame.to_ndarray()
        if arr.ndim == 2:
            arr = arr.mean(axis=0)
        in_sr = int(frame.sample_rate)
        pcm_chunks.append(arr.astype(np.float32))
    if not pcm_chunks:
        return np.zeros(0, dtype=np.int16), target_sr
    audio = np.concatenate(pcm_chunks)
    if in_sr != target_sr and audio.size > 0:
        ratio = target_sr / in_sr
        new_len = max(1, int(len(audio) * ratio))
        x_old = np.linspace(0, 1, num=len(audio), endpoint=False)
        x_new = np.linspace(0, 1, num=new_len, endpoint=False)
        audio = np.interp(x_new, x_old, audio)
    audio = np.clip(audio, -1.0, 1.0)
    audio_i16 = (audio * 32767.0).astype(np.int16)
    return audio_i16, target_sr


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


async def _edge_audio_stream(text: str, voice: str) -> AsyncIterator[bytes]:
    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(text, voice)
            async for event in communicate.stream():
                if event["type"] == "audio" and event.get("data"):
                    yield event["data"]
            return
        except Exception:
            if attempt == 2:
                raise
            log.warning("Edge TTS stream failed; retrying", exc_info=True)
            await asyncio.sleep(0.3 * (attempt + 1))


async def _feed_ffmpeg_stdin(
    proc: asyncio.subprocess.Process,
    audio_iter: AsyncIterator[bytes],
) -> None:
    assert proc.stdin is not None
    try:
        async for data in audio_iter:
            proc.stdin.write(data)
            await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            proc.stdin.close()
            await proc.stdin.wait_closed()


def _pcm_bytes_to_chunk(raw: bytes, sample_rate: int) -> AudioChunk | None:
    sample_count = len(raw) // 2
    if sample_count <= 0:
        return None
    if len(raw) != sample_count * 2:
        raw = raw[: sample_count * 2]
    pcm = np.frombuffer(raw, dtype=np.int16).copy()
    return AudioChunk(
        data=pcm,
        sample_rate=sample_rate,
        duration_ms=1000.0 * sample_count / sample_rate,
    )


async def _stream_decode_mp3_to_pcm_chunks(
    audio_iter: AsyncIterator[bytes],
    target_sr: int,
    chunk_ms: float,
) -> AsyncIterator[AudioChunk]:
    async for chunk in _stream_decode_audio_to_pcm_chunks(
        audio_iter,
        target_sr,
        chunk_ms,
        input_format="mp3",
    ):
        yield chunk


async def _stream_decode_audio_to_pcm_chunks(
    audio_iter: AsyncIterator[bytes],
    target_sr: int,
    chunk_ms: float,
    *,
    input_format: str | None = None,
) -> AsyncIterator[AudioChunk]:
    """Decode incoming compressed/container audio through ffmpeg into PCM chunks."""
    chunk_bytes = max(2, int(target_sr * (chunk_ms / 1000.0)) * 2)
    if chunk_bytes % 2:
        chunk_bytes += 1
    read_size = max(4096, min(chunk_bytes, 65536))
    input_args = ["-f", input_format] if input_format else []

    proc = await asyncio.create_subprocess_exec(
        _ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "1024",
        "-analyzeduration",
        "0",
        *input_args,
        "-i",
        "pipe:0",
        "-vn",
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(target_sr),
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None

    writer = asyncio.create_task(_feed_ffmpeg_stdin(proc, audio_iter))
    pcm_buffer = bytearray()
    yielded_audio = False
    try:
        while True:
            raw = await proc.stdout.read(read_size)
            if not raw:
                break
            pcm_buffer.extend(raw)
            while len(pcm_buffer) >= chunk_bytes:
                chunk = _pcm_bytes_to_chunk(bytes(pcm_buffer[:chunk_bytes]), target_sr)
                del pcm_buffer[:chunk_bytes]
                if chunk is not None:
                    yielded_audio = True
                    yield chunk
        if len(pcm_buffer) % 2:
            pcm_buffer = pcm_buffer[:-1]
        if pcm_buffer:
            chunk = _pcm_bytes_to_chunk(bytes(pcm_buffer), target_sr)
            if chunk is not None:
                yielded_audio = True
                yield chunk
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            if proc.returncode is None:
                proc.kill()
        raise
    finally:
        with contextlib.suppress(Exception):
            await writer

    rc = await proc.wait()
    if rc not in (0, None) and not yielded_audio:
        raise RuntimeError(f"ffmpeg TTS stream decode failed with exit code {rc}")
    if rc not in (0, None):
        log.warning(
            "ffmpeg TTS stream decode exited with code %s after yielding audio; ignoring tail error",
            rc,
        )


class EdgeTTSAdapter:
    """Microsoft Edge TTS (edge-tts); streams MP3 through ffmpeg into PCM chunks."""

    def __init__(
        self,
        default_voice: str = "zh-CN-XiaoxiaoNeural",
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
    ) -> None:
        self.default_voice = default_voice
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        v = voice or self.default_voice
        if _env_bool("OPENTALKING_TTS_STREAMING_DECODE", True):
            try:
                async for chunk in _stream_decode_mp3_to_pcm_chunks(
                    _edge_audio_stream(text, v),
                    self.sample_rate,
                    self.chunk_ms,
                ):
                    yield chunk
                return
            except FileNotFoundError:
                raise RuntimeError(
                    "ffmpeg is required for streaming Edge TTS decode. "
                    "Install ffmpeg or set OPENTALKING_TTS_STREAMING_DECODE=0 "
                    "to use the legacy full-buffer fallback."
                ) from None

        parts: list[bytes] = []
        async for data in _edge_audio_stream(text, v):
            parts.append(data)
        data = b"".join(parts)
        if not data:
            return
        pcm, sr = _decode_mp3_to_pcm16_mono(data, self.sample_rate)
        for chunk in _split_pcm_chunks(pcm, sr, self.chunk_ms):
            yield chunk
