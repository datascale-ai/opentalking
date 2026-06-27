from __future__ import annotations

import base64
import queue
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import httpx


def _write_pcm_queue_to_wav(
    chunk_queue: "queue.Queue[bytes | None]",
    wav_path: Path,
    *,
    sample_rate: int,
) -> None:
    chunks: list[bytes] = []
    while True:
        chunk = chunk_queue.get()
        if chunk is None:
            break
        if chunk:
            chunks.append(bytes(chunk))
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(chunks))


class OpenAICompatibleSTTAdapter:
    """OpenAI Audio Transcriptions compatible STT adapter."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        language: str = "",
        response_format: str = "json",
        protocol: str = "audio_transcriptions",
        audio_format: str = "wav",
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.language = language.strip()
        self.response_format = (response_format or "json").strip().lower()
        self.protocol = (protocol or "audio_transcriptions").strip().lower()
        self.audio_format = (audio_format or "wav").strip().lower()

    def transcribe_wav(self, wav_path: str | Path) -> tuple[str, float]:
        if not self.api_key:
            raise RuntimeError("OpenAI-compatible STT selected but OPENTALKING_STT_OPENAI_API_KEY is empty.")
        if not self.base_url:
            raise RuntimeError("OpenAI-compatible STT selected but OPENTALKING_STT_OPENAI_BASE_URL is empty.")
        if not self.model:
            raise RuntimeError("OpenAI-compatible STT selected but OPENTALKING_STT_OPENAI_MODEL is empty.")

        path = Path(wav_path)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
        t0 = time.perf_counter()
        with httpx.Client(timeout=timeout) as client:
            if self.protocol in {"chat_completions", "chat"}:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                data_url = f"data:audio/{self.audio_format};base64,{encoded}"
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {"data": data_url, "format": self.audio_format},
                                }
                            ],
                        }
                    ],
                }
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            else:
                data: dict[str, str] = {"model": self.model}
                if self.language:
                    data["language"] = self.language
                if self.response_format:
                    data["response_format"] = self.response_format
                with path.open("rb") as fh:
                    resp = client.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers=headers,
                        data=data,
                        files={"file": (path.name or "speech.wav", fh, "audio/wav")},
                    )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"OpenAI-compatible STT failed ({exc.response.status_code}): {resp.text.strip()}"
            ) from exc
        return self._extract_text(resp), elapsed_ms

    def transcribe_pcm_queue(
        self,
        chunk_queue: "queue.Queue[bytes | None]",
        *,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            _write_pcm_queue_to_wav(chunk_queue, wav_path, sample_rate=sample_rate)
            return self.transcribe_wav(wav_path)
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _extract_text(self, resp: httpx.Response) -> str:
        if self.response_format in {"text", "srt", "vtt"}:
            return resp.text.strip()
        try:
            payload: Any = resp.json()
        except ValueError:
            return resp.text.strip()
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("sentence")
            if isinstance(text, str):
                return text.strip()
            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                message = first.get("message") if isinstance(first, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str):
                    return content.strip()
            segments = payload.get("segments")
            if isinstance(segments, list):
                return "".join(str(item.get("text", "")) for item in segments if isinstance(item, dict)).strip()
        if isinstance(payload, str):
            return payload.strip()
        return ""
