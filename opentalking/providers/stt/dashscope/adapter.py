"""百炼 DashScope 语音识别（Paraformer 实时模型）。

- **文件路径**：``Recognition.call(wav)``（SDK 内部按块走 WebSocket）。
- **真流式**：``Recognition.start()`` → ``send_audio_frame(pcm)`` → ``stop()``，
  适用于浏览器经 WebSocket 下发 **PCM s16le mono 16kHz** 分块。
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

log = logging.getLogger(__name__)


class _NoopRecognitionCallback(RecognitionCallback):
    """Recognition 构造要求 callback；同步 call() 路径在内部汇总结果，此处仅占位。"""

    def on_event(self, result: RecognitionResult) -> None:
        pass


class _StreamingTextCollector(RecognitionCallback):
    """流式识别：汇总 ``sentence_end`` 分句；否则保留最后一次部分文本。"""

    def __init__(self) -> None:
        self._segments: list[str] = []
        self._last_partial = ""
        self._lock = threading.Lock()
        self.error_message: str | None = None

    def on_event(self, result: RecognitionResult) -> None:
        with self._lock:
            pushed = False
            sentences = result.get_sentence()
            if isinstance(sentences, list):
                for item in sentences:
                    if (
                        isinstance(item, dict)
                        and item.get("sentence_end")
                        and item.get("text")
                    ):
                        self._segments.append(str(item["text"]).strip())
                        pushed = True
            if not pushed:
                t = recognition_result_to_text(result)
                if t:
                    self._last_partial = t

    def on_error(self, result: RecognitionResult) -> None:
        self.error_message = getattr(result, "message", None) or str(result)

    def combined_text(self) -> str:
        with self._lock:
            merged = "".join(self._segments).strip()
            return merged if merged else self._last_partial.strip()


def _dashscope_api_key() -> str:
    direct = os.environ.get("OPENTALKING_STT_DASHSCOPE_API_KEY", "").strip()
    if direct:
        return direct
    try:
        from opentalking.core.config import get_settings

        settings = get_settings()
        return getattr(settings, "stt_dashscope_api_key", "").strip()
    except Exception:
        return ""


def _ffmpeg_bin() -> str:
    return os.environ.get("OPENTALKING_FFMPEG_BIN", "ffmpeg").strip() or "ffmpeg"


def _stt_model() -> str:
    direct = os.environ.get("OPENTALKING_STT_DASHSCOPE_MODEL", "").strip()
    if direct:
        return direct
    try:
        from opentalking.core.config import get_settings

        settings = get_settings()
        return getattr(settings, "stt_dashscope_model", "").strip() or "paraformer-realtime-v2"
    except Exception:
        return "paraformer-realtime-v2"


def _language_hints() -> list[str] | None:
    raw = os.environ.get("OPENTALKING_STT_LANGUAGE_HINTS", "").strip()
    if not raw:
        return ["zh", "en"]
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or None


def recognition_result_to_text(result: RecognitionResult) -> str:
    """从 Recognition.call 返回值解析中文/英文拼接文本。"""
    sentences = result.get_sentence()
    if sentences is None:
        out = getattr(result, "output", None)
        if isinstance(out, dict):
            s = out.get("sentence")
            if isinstance(s, dict) and s.get("text"):
                return str(s["text"]).strip()
        return ""

    if isinstance(sentences, dict):
        return str(sentences.get("text", "")).strip()

    parts: list[str] = []
    for item in sentences:
        if isinstance(item, dict) and item.get("text"):
            parts.append(str(item["text"]))
    merged = "".join(parts).strip()
    if merged:
        return merged

    out = getattr(result, "output", None)
    if isinstance(out, dict):
        s = out.get("sentence")
        if isinstance(s, dict) and s.get("text"):
            return str(s["text"]).strip()
    return ""


async def ensure_wav_16k_mono(src_path: Path, wav_out: Path) -> None:
    """将浏览器上传的 webm/ogg/mp4 等转为 16kHz 单声道 WAV（Paraformer 常用格式）。"""
    ff = _ffmpeg_bin()
    log.debug("STT ffmpeg: %s -> %s (src size=%s)", src_path, wav_out, src_path.stat().st_size)
    proc = await asyncio.create_subprocess_exec(
        ff,
        "-y",
        "-i",
        str(src_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(wav_out),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode(errors="replace")[-800:]
        log.warning("STT ffmpeg failed rc=%s: %s", proc.returncode, msg)
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {msg}")


async def decode_audio_file_to_pcm_i16(src_path: Path) -> np.ndarray:
    """将任意 ffmpeg 可读音频解码为 16kHz mono PCM int16。"""
    ff = _ffmpeg_bin()
    proc = await asyncio.create_subprocess_exec(
        ff,
        "-y",
        "-i",
        str(src_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode(errors="replace")[-800:]
        log.warning("audio decode ffmpeg failed rc=%s: %s", proc.returncode, msg)
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {msg}")
    return np.frombuffer(stdout, dtype=np.int16)


def _recognize_wav_sync(wav_path: Path) -> tuple[str, float]:
    """调用百炼 Recognition；返回 (文本, Recognition.call 墙钟毫秒)。"""
    import dashscope

    api_key = _dashscope_api_key()
    if not api_key:
        raise RuntimeError(
            "缺少 DashScope STT API Key：请设置 OPENTALKING_STT_DASHSCOPE_API_KEY。"
        )

    dashscope.api_key = api_key
    hints = _language_hints()
    kwargs: dict = {}
    if hints:
        kwargs["language_hints"] = hints

    model = _stt_model()
    rc = Recognition(
        model=model,
        callback=_NoopRecognitionCallback(),
        format="wav",
        sample_rate=16000,
        **kwargs,
    )
    t_call = time.perf_counter()
    try:
        result = rc.call(str(wav_path))
    except Exception as e:
        log.exception("STT Recognition.call raised")
        raise RuntimeError(f"DashScope STT 调用异常: {e}") from e

    call_ms = (time.perf_counter() - t_call) * 1000.0

    sc = getattr(result, "status_code", None)
    try:
        sc_int = int(sc) if sc is not None else None
    except (TypeError, ValueError):
        sc_int = None
    if sc_int != 200:
        msg = getattr(result, "message", None) or getattr(result, "code", None)
        req = getattr(result, "request_id", None)
        log.warning(
            "STT DashScope 非成功: status_code=%s message=%s code=%s request_id=%s",
            sc,
            getattr(result, "message", None),
            getattr(result, "code", None),
            req,
        )
        detail = msg or "STT failed"
        raise RuntimeError(
            f"百炼语音识别失败（HTTP {sc}）: {detail}。"
            "请核对 API Key、模型名 OPENTALKING_STT_DASHSCOPE_MODEL、账号是否开通语音识别。"
        )

    text = recognition_result_to_text(result)
    if not text.strip():
        log.warning(
            "STT 返回空文本: output=%s",
            getattr(result, "output", None),
        )
    return text, call_ms


def transcribe_pcm_chunk_queue_sync(chunk_queue: "queue.Queue[bytes | None]") -> tuple[str, float]:
    """PCM s16le mono 16kHz 分块流式识别。

    ``chunk_queue`` 中依次放入音频 ``bytes``；放入 ``None`` 表示本段音频已结束，
    随后将调用 ``Recognition.stop()``。
    """
    import dashscope

    api_key = _dashscope_api_key()
    if not api_key:
        raise RuntimeError(
            "缺少 DashScope STT API Key：请设置 OPENTALKING_STT_DASHSCOPE_API_KEY。"
        )

    dashscope.api_key = api_key
    hints = _language_hints()
    kwargs: dict = {}
    if hints:
        kwargs["language_hints"] = hints

    collector = _StreamingTextCollector()
    model = _stt_model()
    rc = Recognition(
        model=model,
        callback=collector,
        format="pcm",
        sample_rate=16000,
        **kwargs,
    )
    t0 = time.perf_counter()
    try:
        rc.start()
        while True:
            chunk = chunk_queue.get()
            if chunk is None:
                break
            if chunk:
                rc.send_audio_frame(chunk)
    finally:
        try:
            rc.stop()
        except Exception:  # noqa: BLE001
            log.exception("STT streaming Recognition.stop failed")

    dashscope_ms = (time.perf_counter() - t0) * 1000.0

    if collector.error_message:
        raise RuntimeError(f"DashScope 流式 STT 错误: {collector.error_message}")

    text = collector.combined_text()
    if not text.strip():
        log.warning("STT 流式识别返回空文本")

    return text, dashscope_ms


async def transcribe_audio_file_path(upload_path: Path) -> str:
    """上传的任意 ffmpeg 可读音频 → 临时 WAV → DashScope 识别。"""
    t_total0 = time.perf_counter()
    upload_sz = upload_path.stat().st_size

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    try:
        t_ff0 = time.perf_counter()
        await ensure_wav_16k_mono(upload_path, wav_path)
        ffmpeg_ms = (time.perf_counter() - t_ff0) * 1000.0

        wav_sz = wav_path.stat().st_size
        # PCM16 单声道 16kHz：约 32000 字节/秒；WAV 头约 44 字节（粗略估算时长）
        pcm_bytes = max(0, wav_sz - 44)
        est_audio_s = pcm_bytes / 32000.0

        text, dashscope_ms = await asyncio.to_thread(_recognize_wav_sync, wav_path)

        total_ms = (time.perf_counter() - t_total0) * 1000.0
        preview = (text.strip()[:24] + "…") if len(text.strip()) > 24 else text.strip()
        log.info(
            "STT timing: model=%s upload_bytes=%d ffmpeg_ms=%.0f wav_bytes=%d ~audio=%.2fs "
            "dashscope_ms=%.0f total_ms=%.0f text_chars=%d preview=%r",
            _stt_model(),
            upload_sz,
            ffmpeg_ms,
            wav_sz,
            est_audio_s,
            dashscope_ms,
            total_ms,
            len(text.strip()),
            preview,
        )
        return text
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass
