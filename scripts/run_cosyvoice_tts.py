from __future__ import annotations

import argparse
import asyncio
import json
import sys
import wave
from datetime import datetime
from pathlib import Path

import numpy as np


def _bootstrap_local_paths(root: Path) -> None:
    sys.path[:0] = [str(root), str(root / "src")]


ROOT = Path(__file__).resolve().parents[1]
_bootstrap_local_paths(ROOT)

from opentalking.core.config import get_settings
from opentalking.tts.cosyvoice.adapter import CosyVoiceAdapter


def _save_wav(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.astype(np.int16, copy=False).tobytes())


async def _synthesize_pcm(adapter: CosyVoiceAdapter, text: str) -> np.ndarray:
    parts: list[np.ndarray] = []
    async for chunk in adapter.synthesize_stream(text):
        parts.append(np.asarray(chunk.data, dtype=np.int16).reshape(-1).copy())
    if not parts:
        raise RuntimeError("CosyVoice produced no audio chunks.")
    return np.concatenate(parts).astype(np.int16, copy=False)


def main() -> None:
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Run CosyVoice TTS and save a wav file.")
    parser.add_argument(
        "--text",
        default=(
            "大家好，这是一条使用参考音频进行声线复刻生成的测试语音。"
            "现在 CosyVoice 和 Whisper 的整条链路已经成功打通，语音输出也已经生成。"
        ),
        help="Text to synthesize.",
    )
    parser.add_argument(
        "--reference-audio",
        default=settings.tts_clone_reference_audio,
        help="Reference audio used for voice cloning.",
    )
    parser.add_argument(
        "--model-dir",
        default=settings.tts_cosyvoice_model_dir,
        help="CosyVoice model directory.",
    )
    parser.add_argument(
        "--repo-dir",
        default=settings.tts_cosyvoice_repo_dir,
        help="CosyVoice repository directory.",
    )
    parser.add_argument(
        "--mode",
        default=settings.tts_cosyvoice_mode,
        choices=("zero_shot", "instruct2"),
        help="CosyVoice inference mode.",
    )
    parser.add_argument(
        "--prompt-source",
        default=settings.tts_cosyvoice_prompt_source,
        choices=("asr", "manual"),
        help="How to build the prompt text passed to CosyVoice.",
    )
    parser.add_argument(
        "--prompt-prefix",
        default=settings.tts_cosyvoice_prompt_prefix,
        help="Prompt prefix for ASR prompt mode.",
    )
    parser.add_argument(
        "--prompt-text",
        default=settings.tts_cosyvoice_prompt_text,
        help="Full prompt text for manual mode. Must contain <|endofprompt|>.",
    )
    parser.add_argument(
        "--prompt-max-seconds",
        type=float,
        default=settings.tts_cosyvoice_prompt_max_seconds,
        help="Maximum duration of prompt audio kept from the reference wav.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=settings.tts_sample_rate,
        help="Output sample rate.",
    )
    parser.add_argument(
        "--chunk-ms",
        type=float,
        default=40.0,
        help="Chunk size used during synthesis.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=settings.tts_cosyvoice_speed,
        help="Speech speed passed to CosyVoice.",
    )
    parser.add_argument(
        "--asr-model-path",
        default=settings.tts_asr_model_path,
        help="Whisper checkpoint path used for ASR prompt extraction.",
    )
    parser.add_argument(
        "--asr-language",
        default=settings.tts_asr_language,
        help="Language hint passed to Whisper.",
    )
    parser.add_argument(
        "--cache-dir",
        default=settings.tts_clone_cache_dir,
        help="Cache directory for prepared prompt audio and ASR outputs.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default=settings.ffmpeg_bin,
        help="ffmpeg binary used to convert prompt audio.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output wav path. If omitted, a timestamped file is created under output/cosyvoice_tts.",
    )
    args = parser.parse_args()

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else (ROOT / "output" / "cosyvoice_tts" / f"cosyvoice_clone_{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav")
    )

    adapter = CosyVoiceAdapter(
        model_dir=Path(args.model_dir).expanduser().resolve(),
        repo_dir=Path(args.repo_dir).expanduser().resolve(),
        reference_audio=Path(args.reference_audio).expanduser().resolve(),
        mode=args.mode,
        prompt_source=args.prompt_source,
        prompt_prefix=args.prompt_prefix,
        prompt_text=args.prompt_text,
        prompt_max_seconds=float(args.prompt_max_seconds),
        sample_rate=int(args.sample_rate),
        chunk_ms=float(args.chunk_ms),
        speed=float(args.speed),
        asr_model_path=Path(args.asr_model_path).expanduser().resolve(),
        asr_language=args.asr_language,
        cache_dir=Path(args.cache_dir).expanduser().resolve(),
        ffmpeg_bin=args.ffmpeg_bin,
    )

    pcm = asyncio.run(_synthesize_pcm(adapter, args.text))
    _save_wav(output_path, pcm, int(args.sample_rate))

    print(
        json.dumps(
            {
                "output": str(output_path),
                "text": args.text,
                "sample_rate": int(args.sample_rate),
                "duration_sec": round(float(pcm.shape[0]) / float(args.sample_rate), 3),
                "reference_audio": str(Path(args.reference_audio).expanduser().resolve()),
                "model_dir": str(Path(args.model_dir).expanduser().resolve()),
                "asr_model_path": str(Path(args.asr_model_path).expanduser().resolve()),
                "mode": args.mode,
                "prompt_source": args.prompt_source,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
