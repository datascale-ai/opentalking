from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
import soundfile as sf


def _normalize_device(device: str) -> str:
    raw = device.strip().lower()
    if raw != "auto":
        return raw
    try:
        import torch
    except Exception:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _resolve_xtts_source(model_name: str) -> tuple[str, str | None]:
    candidate = Path(model_name).expanduser()
    if candidate.is_dir():
        config_path = candidate / "config.json"
        model_path = candidate / "model.pth"
        if not config_path.is_file() or not model_path.is_file():
            raise RuntimeError(
                "Local XTTS model directory must contain config.json and model.pth: "
                f"{candidate}"
            )
        return str(candidate.resolve()), str(config_path.resolve())
    return model_name, None


def _patch_torchaudio_load_if_needed() -> None:
    try:
        import torchaudio
    except Exception:
        return

    try:
        from torchcodec.decoders import AudioDecoder  # noqa: F401
        return
    except Exception:
        pass

    def _soundfile_load(path, *args, **kwargs):
        import torch

        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        audio = torch.from_numpy(np.asarray(data.T, dtype=np.float32))
        return audio, int(sample_rate)

    torchaudio.load = _soundfile_load


def _load_runtime(model_name: str, device: str):
    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    _patch_torchaudio_load_if_needed()

    from TTS.api import TTS

    model_source, config_path = _resolve_xtts_source(model_name)
    device = _normalize_device(device)
    gpu = device.startswith("cuda")
    with contextlib.redirect_stdout(sys.stderr):
        if config_path is None:
            runtime = TTS(model_name=model_source, progress_bar=False, gpu=gpu)
        else:
            runtime = TTS(
                model_path=model_source,
                config_path=config_path,
                progress_bar=False,
                gpu=gpu,
            )
        if hasattr(runtime, "to"):
            moved = runtime.to(device)
            if moved is not None:
                runtime = moved
    return runtime


def _synthesize(runtime, *, text: str, language: str, reference_audio: str, output_path: str) -> None:
    with contextlib.redirect_stdout(sys.stderr):
        runtime.tts_to_file(
            text=text,
            language=language,
            speaker_wav=reference_audio,
            file_path=output_path,
            split_sentences=True,
        )


def _handle_command(runtime, payload: dict[str, object]) -> dict[str, object]:
    cmd = str(payload.get("cmd", "")).strip().lower()
    text = str(payload.get("text", "")).strip()
    language = str(payload.get("language", "")).strip() or "zh-cn"
    reference_audio = str(payload.get("reference_audio", "")).strip()
    if not reference_audio:
        raise RuntimeError("reference_audio is required")

    if cmd == "warmup":
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = tmp.name
        try:
            _synthesize(
                runtime,
                text=text or "你好",
                language=language,
                reference_audio=reference_audio,
                output_path=out_path,
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(out_path)
        return {"status": "ok"}

    if cmd == "synthesize":
        output_path = str(payload.get("output_path", "")).strip()
        if not output_path:
            raise RuntimeError("output_path is required")
        _synthesize(
            runtime,
            text=text,
            language=language,
            reference_audio=reference_audio,
            output_path=output_path,
        )
        return {"status": "ok", "output_path": output_path}

    if cmd == "ping":
        return {"status": "ok"}

    raise RuntimeError(f"unsupported cmd: {cmd}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    runtime = _load_runtime(args.model_name, args.device)

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
            response = _handle_command(runtime, payload)
        except Exception as exc:  # noqa: BLE001
            response = {"status": "error", "message": str(exc)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
