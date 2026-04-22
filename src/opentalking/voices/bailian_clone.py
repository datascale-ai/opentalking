"""百炼声音复刻：CosyVoice（URL + VoiceEnrollmentService）、Qwen（base64 + HTTP）。"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

DASHSCOPE_CUSTOMIZATION_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"


def _dashscope_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        try:
            from opentalking.core.config import get_settings

            key = (get_settings().llm_api_key or "").strip()
        except Exception:
            pass
    if not key:
        raise RuntimeError("需要 DASHSCOPE_API_KEY 或 OPENTALKING_LLM_API_KEY（百炼 API Key）。")
    return key


def _ffmpeg_bin() -> str:
    try:
        from opentalking.core.config import get_settings

        return (get_settings().ffmpeg_bin or "ffmpeg").strip() or "ffmpeg"
    except Exception:
        return os.environ.get("OPENTALKING_FFMPEG_BIN", "ffmpeg")


def convert_audio_to_wav_24k_mono(upload_bytes: bytes, suffix: str) -> bytes:
    """将浏览器上传（webm/wav/mp3 等）转为 24kHz 单声道 s16 WAV（百炼常见要求）。"""
    ffmpeg = _ffmpeg_bin()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fin:
        fin.write(upload_bytes)
        fin.flush()
        in_path = fin.name
    out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fout:
            out_path = fout.name
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            in_path,
            "-ac",
            "1",
            "-ar",
            "24000",
            "-f",
            "wav",
            out_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return Path(out_path).read_bytes()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg 转码失败: {e.stderr.decode(errors='replace')[:500]}") from e
    finally:
        Path(in_path).unlink(missing_ok=True)
        if out_path:
            Path(out_path).unlink(missing_ok=True)


def clone_cosyvoice_voice(
    *,
    target_model: str,
    prefix: str,
    public_audio_url: str,
) -> str:
    """调用 DashScope VoiceEnrollmentService（音频须为 public_audio_url 可访问）。"""
    import dashscope
    from dashscope.audio.tts_v2 import VoiceEnrollmentService

    dashscope.api_key = _dashscope_api_key()
    prefix_clean = prefix.strip().lower()
    if not re.fullmatch(r"[a-z0-9]{1,9}", prefix_clean):
        raise ValueError("音色前缀须为 1～9 位小写字母或数字")
    svc = VoiceEnrollmentService()
    voice_id = svc.create_voice(
        target_model=target_model.strip(),
        prefix=prefix_clean,
        url=public_audio_url,
        language_hints=["zh"],
    )
    return str(voice_id)


def clone_qwen_voice(
    *,
    wav_bytes: bytes,
    target_model: str,
    preferred_name: str,
    audio_mime: str = "audio/wav",
) -> str:
    """qwen-voice-enrollment：base64 data URI，无需公网 URL。"""
    api_key = _dashscope_api_key()
    b64 = base64.standard_b64encode(wav_bytes).decode("ascii")
    data_uri = f"data:{audio_mime};base64,{b64}"
    preferred = preferred_name.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,19}", preferred):
        raise ValueError("preferred_name 须以小写字母开头，仅含小写、数字、下划线，≤20 字符")

    payload: dict = {
        "model": "qwen-voice-enrollment",
        "input": {
            "action": "create",
            "target_model": target_model.strip(),
            "preferred_name": preferred,
            "audio": {"data": data_uri},
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=180.0) as client:
        r = client.post(DASHSCOPE_CUSTOMIZATION_URL, json=payload, headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"百炼千问复刻失败 HTTP {r.status_code}: {r.text[:800]}")
    data = r.json()
    out = data.get("output") or {}
    voice = out.get("voice")
    if not voice:
        raise RuntimeError(f"百炼返回无 voice 字段: {data!r}")
    return str(voice)
