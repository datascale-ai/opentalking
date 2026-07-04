from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from opentalking.models.quicktalk.runtime import (
    MultiFaceRealtimeV3Worker,
    validate_multiface_script,
)


def load_multiface_script(path: Path) -> dict[str, Any]:
    script_path = path.expanduser().resolve()
    payload = json.loads(script_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("multiface script must be a JSON object")
    for segment in payload.get("segments", []):
        if not isinstance(segment, dict):
            continue
        raw_audio = segment.get("audio")
        if not raw_audio:
            continue
        audio_path = Path(str(raw_audio)).expanduser()
        if not audio_path.is_absolute():
            audio_path = script_path.parent / audio_path
        segment["audio"] = str(audio_path.resolve())
    validate_multiface_script(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a fixed-template multi-face QuickTalk video from a speaker script."
    )
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--template-video", required=True)
    parser.add_argument("--script", required=True, help="JSON file with speaker_faces and segments")
    parser.add_argument("--audio", required=True, help="Final mixed audio track to mux")
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--face-cache-dir", default=None)
    parser.add_argument("--no-face-cache", action="store_true")
    parser.add_argument("--output-transform", choices=["rgb", "bgr", "tanh_rgb", "tanh_bgr"], default="bgr")
    parser.add_argument("--scale-h", type=float, default=1.6)
    parser.add_argument("--scale-w", type=float, default=3.6)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--max-template-seconds", type=float, default=None)
    parser.add_argument("--neck-fade-start", type=float, default=None)
    parser.add_argument("--neck-fade-end", type=float, default=None)
    parser.add_argument("--paste-strength", type=float, default=1.0)
    parser.add_argument("--mouth-hold-ms", type=int, default=0)
    parser.add_argument("--tail-fade-ms", type=int, default=0)
    parser.add_argument("--tail-fade-region", choices=["roi", "mouth"], default="mouth")
    parser.add_argument("--tail-fade-mouth-start", type=float, default=0.5)
    parser.add_argument("--tail-fade-mouth-ramp", type=float, default=0.18)
    parser.add_argument(
        "--idle-anchor-mode",
        choices=["none", "mouth", "face"],
        default="none",
        help="Deprecated compatibility option; segment transitions now fade to current template frames.",
    )
    parser.add_argument("--idle-anchor-start", type=float, default=0.55)
    parser.add_argument("--model-backend", choices=["auto", "pth", "onnx"], default="auto")
    parser.add_argument("--video-codec", default="libx264")
    parser.add_argument("--ffmpeg-preset", default="veryfast")
    parser.add_argument("--ffmpeg-tune", default="zerolatency")
    parser.add_argument("--crf", type=int, default=18)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asset_root = Path(args.asset_root).expanduser().resolve()
    if asset_root.name != "hdModule" and (asset_root / "hdModule" / "checkpoints").exists():
        asset_root = asset_root / "hdModule"
    face_cache_dir = None
    if not args.no_face_cache:
        face_cache_dir = (
            Path(args.face_cache_dir).expanduser().resolve()
            if args.face_cache_dir
            else asset_root / ".face_cache_v3"
        )
    script = load_multiface_script(Path(args.script))
    worker = MultiFaceRealtimeV3Worker(
        asset_root=asset_root,
        template_video=Path(args.template_video).expanduser().resolve(),
        face_cache_dir=face_cache_dir,
        device=args.device,
        output_transform=args.output_transform,
        scale_h=args.scale_h,
        scale_w=args.scale_w,
        resolution=args.resolution,
        max_template_seconds=args.max_template_seconds,
        neck_fade_start=args.neck_fade_start,
        neck_fade_end=args.neck_fade_end,
        paste_strength=args.paste_strength,
        mouth_hold_ms=args.mouth_hold_ms,
        tail_fade_ms=args.tail_fade_ms,
        tail_fade_region=args.tail_fade_region,
        tail_fade_mouth_start=args.tail_fade_mouth_start,
        tail_fade_mouth_ramp=args.tail_fade_mouth_ramp,
        idle_anchor_mode=args.idle_anchor_mode,
        idle_anchor_start=args.idle_anchor_start,
        model_backend=args.model_backend,
    )
    stats = worker.generate_video_from_script(
        script,
        Path(args.audio).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        video_codec=args.video_codec,
        ffmpeg_preset=args.ffmpeg_preset,
        ffmpeg_tune=args.ffmpeg_tune or None,
        crf=args.crf,
    )
    print(json.dumps({"output": args.output, "frames": stats.frames, "fps": stats.fps}, indent=2))


if __name__ == "__main__":
    main()
