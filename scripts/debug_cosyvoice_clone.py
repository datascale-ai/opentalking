from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


def _bootstrap_local_paths(root: Path) -> None:
    sys.path[:0] = [str(root), str(root / "src")]


ROOT = Path(__file__).resolve().parents[1]
_bootstrap_local_paths(ROOT)

from opentalking.core.config import get_settings
from opentalking.models.wav2lip.official_runtime import run_official_inference
from opentalking.tts.cosyvoice.adapter import CosyVoiceAdapter, _get_cosyvoice_runtime


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _slugify(value: str) -> str:
    slug = []
    for char in value.strip().lower():
        if char.isalnum():
            slug.append(char)
        elif char in {"-", "_"}:
            slug.append(char)
        else:
            slug.append("-")
    compact = "".join(slug).strip("-")
    while "--" in compact:
        compact = compact.replace("--", "-")
    return compact or "run"


def _save_wav(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.astype(np.int16).tobytes())


def _resolve_avatar_path(avatar: str) -> Path:
    avatar_path = Path(avatar).expanduser()
    if avatar_path.is_dir():
        return avatar_path.resolve()
    candidate = ROOT / "examples" / "avatars" / avatar
    if candidate.is_dir():
        return candidate.resolve()
    raise FileNotFoundError(f"Avatar not found: {avatar}")


def _load_avatar_fps(avatar_path: Path) -> int:
    manifest_path = avatar_path / "manifest.json"
    if not manifest_path.is_file():
        return 25
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return max(1, int(manifest.get("fps", 25)))


def _prepare_prompt_audio(
    *,
    source_audio: Path,
    out_path: Path,
    prompt_max_seconds: float,
    sample_rate: int,
    ffmpeg_bin: str,
) -> None:
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source_audio),
            "-t",
            f"{prompt_max_seconds:.3f}",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(out_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _load_whisper_runtime(model_path: Path, device: str):
    try:
        import whisper
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("openai-whisper is required for CosyVoice ASR debugging.") from exc
    return whisper.load_model(str(model_path), device=device)


def _transcribe_prompt(
    *,
    prompt_wav: Path,
    model_path: Path,
    language: str,
) -> dict[str, Any]:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("torch is required for Whisper transcription.") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    whisper_model = _load_whisper_runtime(model_path, device=device)
    result = whisper_model.transcribe(
        str(prompt_wav),
        language=language,
        fp16=(device == "cuda"),
        verbose=False,
    )
    result["device"] = device
    result["model_path"] = str(model_path.resolve())
    return result


async def _synthesize_pcm(adapter: CosyVoiceAdapter, text: str) -> np.ndarray:
    parts: list[np.ndarray] = []
    async for chunk in adapter.synthesize_stream(text):
        parts.append(np.asarray(chunk.data, dtype=np.int16).reshape(-1).copy())
    if not parts:
        raise RuntimeError("CosyVoice produced no audio chunks.")
    return np.concatenate(parts).astype(np.int16, copy=False)


def _build_run_dir(output_root: Path, avatar: str, asr_model_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder_name = f"{stamp}-{_slugify(asr_model_path.parent.name)}-{_slugify(avatar)}"
    run_dir = output_root / folder_name
    _ensure_dir(run_dir)
    return run_dir


def main() -> None:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="Debug CosyVoice zero-shot cloning with ASR prompt extraction and Wav2Lip rendering."
    )
    parser.add_argument(
        "--reference-audio",
        default=settings.tts_clone_reference_audio,
        help="Reference audio for voice cloning.",
    )
    parser.add_argument(
        "--text",
        default=(
            "大家好，我现在用更高质量的自动识别提示词测试声线复刻效果。"
            "这一版使用 Whisper large-v3，不做人手修正。"
        ),
        help="Text to synthesize.",
    )
    parser.add_argument("--avatar", default="demo-wav2lip", help="Avatar id or path.")
    parser.add_argument(
        "--output-root",
        default=str(ROOT / "output" / "cosyvoice_runs"),
        help="Root directory used to store per-run outputs.",
    )
    parser.add_argument(
        "--asr-model-path",
        default=settings.tts_asr_model_path,
        help="Path to the Whisper model checkpoint used for prompt transcription.",
    )
    parser.add_argument(
        "--asr-language",
        default=settings.tts_asr_language,
        help="Language hint passed to Whisper.",
    )
    parser.add_argument(
        "--prompt-prefix",
        default=settings.tts_cosyvoice_prompt_prefix,
        help="Prompt prefix passed to CosyVoice before the recognized transcript.",
    )
    parser.add_argument(
        "--prompt-max-seconds",
        type=float,
        default=settings.tts_cosyvoice_prompt_max_seconds,
        help="Maximum prompt duration kept from the reference audio.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=settings.tts_sample_rate,
        help="Output sample rate for synthesized audio.",
    )
    parser.add_argument(
        "--chunk-ms",
        type=float,
        default=40.0,
        help="Audio chunk size used during synthesis.",
    )
    parser.add_argument(
        "--cosyvoice-mode",
        default=settings.tts_cosyvoice_mode,
        choices=("zero_shot", "instruct2"),
        help="CosyVoice inference mode.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=settings.tts_cosyvoice_speed,
        help="Speech speed passed to CosyVoice.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default=settings.ffmpeg_bin,
        help="ffmpeg binary used to convert prompt audio.",
    )
    args = parser.parse_args()

    reference_audio = Path(args.reference_audio).expanduser().resolve()
    if not reference_audio.is_file():
        raise FileNotFoundError(f"Reference audio not found: {reference_audio}")

    asr_model_path = Path(args.asr_model_path).expanduser().resolve()
    if not asr_model_path.is_file():
        raise FileNotFoundError(f"Whisper model not found: {asr_model_path}")

    avatar_path = _resolve_avatar_path(args.avatar)
    avatar_fps = _load_avatar_fps(avatar_path)
    output_root = Path(args.output_root).expanduser().resolve()
    run_dir = _build_run_dir(output_root, avatar_path.name, asr_model_path)

    prompt_wav = run_dir / "prompt.wav"
    prompt_json = run_dir / "asr_prompt.json"
    prompt_txt = run_dir / "prompt_text.txt"
    runtime_prompt_txt = run_dir / "runtime_prompt_text.txt"
    synth_text_path = run_dir / "synthesis_text.txt"
    runtime_synth_text_path = run_dir / "runtime_synthesis_text.txt"
    audio_path = run_dir / "tts.wav"
    render_audio_path = run_dir / "render_input.wav"
    render_video_path = run_dir / "rendered.mp4"
    meta_path = run_dir / "meta.json"
    summary_path = run_dir / "summary.txt"

    _prepare_prompt_audio(
        source_audio=reference_audio,
        out_path=prompt_wav,
        prompt_max_seconds=float(args.prompt_max_seconds),
        sample_rate=16000,
        ffmpeg_bin=args.ffmpeg_bin,
    )

    asr_result = _transcribe_prompt(
        prompt_wav=prompt_wav,
        model_path=asr_model_path,
        language=args.asr_language,
    )
    prompt_json.write_text(
        json.dumps(asr_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    transcript = str(asr_result.get("text", "")).strip()
    if not transcript:
        raise RuntimeError("Whisper produced an empty prompt transcript.")

    full_prompt = f"{args.prompt_prefix}{transcript}"
    prompt_txt.write_text(full_prompt, encoding="utf-8")
    synth_text_path.write_text(args.text, encoding="utf-8")

    adapter = CosyVoiceAdapter(
        model_dir=Path(settings.tts_cosyvoice_model_dir).expanduser().resolve(),
        repo_dir=Path(settings.tts_cosyvoice_repo_dir).expanduser().resolve(),
        reference_audio=reference_audio,
        mode=args.cosyvoice_mode,
        prompt_source="manual",
        prompt_prefix=args.prompt_prefix,
        prompt_text=full_prompt,
        prompt_max_seconds=float(args.prompt_max_seconds),
        sample_rate=int(args.sample_rate),
        chunk_ms=float(args.chunk_ms),
        speed=float(args.speed),
        asr_model_path=asr_model_path,
        asr_language=args.asr_language,
        cache_dir=Path(settings.tts_clone_cache_dir).expanduser().resolve(),
        ffmpeg_bin=args.ffmpeg_bin,
    )
    runtime = _get_cosyvoice_runtime(adapter.model_dir, adapter.repo_dir)
    runtime_synthesis_text, runtime_prompt_text = adapter._prepare_runtime_inputs(
        runtime=runtime,
        text=args.text,
        prompt_text=full_prompt,
    )
    runtime_prompt_txt.write_text(runtime_prompt_text, encoding="utf-8")
    runtime_synth_text_path.write_text(runtime_synthesis_text, encoding="utf-8")
    print(runtime_prompt_text)

    pcm = asyncio.run(_synthesize_pcm(adapter, args.text))
    _save_wav(audio_path, pcm, int(args.sample_rate))

    work_dir, wav_path, video_path = run_official_inference(
        avatar_path=avatar_path,
        pcm=pcm,
        sample_rate=int(args.sample_rate),
        fps=avatar_fps,
        ffmpeg_bin=args.ffmpeg_bin,
    )
    shutil.copy2(wav_path, render_audio_path)
    shutil.copy2(video_path, render_video_path)

    meta = {
        "run_dir": str(run_dir),
        "reference_audio": str(reference_audio),
        "prompt_wav": str(prompt_wav),
        "avatar_path": str(avatar_path),
        "avatar_fps": avatar_fps,
        "prompt_transcript": transcript,
        "prompt_text": full_prompt,
        "runtime_prompt_text": runtime_prompt_text,
        "runtime_synthesis_text": runtime_synthesis_text,
        "synthesis_text": args.text,
        "asr_model_path": str(asr_model_path),
        "asr_language": args.asr_language,
        "cosyvoice_mode": args.cosyvoice_mode,
        "sample_rate": int(args.sample_rate),
        "chunk_ms": float(args.chunk_ms),
        "speed": float(args.speed),
        "audio_duration_sec": round(float(pcm.shape[0]) / float(args.sample_rate), 3),
        "audio_path": str(audio_path),
        "render_input_wav": str(render_audio_path),
        "render_video_path": str(render_video_path),
        "wav2lip_work_dir": str(work_dir),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(
        "\n".join(
            [
                f"run_dir: {run_dir}",
                f"reference_audio: {reference_audio}",
                f"asr_model_path: {asr_model_path}",
                f"prompt_transcript: {transcript}",
                f"runtime_prompt_text: {runtime_prompt_text}",
                f"runtime_synthesis_text: {runtime_synthesis_text}",
                f"audio_path: {audio_path}",
                f"render_video_path: {render_video_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
