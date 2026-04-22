from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import subprocess
import sys
import wave
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _bootstrap_local_paths(root: Path) -> None:
    sys.path[:0] = [str(root), str(root / "src")]


ROOT = Path(__file__).resolve().parents[1]
_bootstrap_local_paths(ROOT)

from opentalking.core.types.frames import AudioChunk
from opentalking.models.musetalk.adapter import MuseTalkAdapter
from opentalking.models.musetalk.face_utils import crop_face_region
from opentalking.tts.coqui.adapter import CoquiXTTSAdapter
from opentalking.tts.edge.adapter import EdgeTTSAdapter
from opentalking.worker.pipeline.render_pipeline import (
    prepare_rendered_chunk_sync,
    reset_avatar_speech_state,
)


@dataclass
class FrameMetric:
    frame_idx: int
    chunk_idx: int
    local_frame_idx: int
    feature_norm: float
    feature_delta_l2: float
    feature_delta_mean_abs: float
    pred_motion_mean_abs: float
    comp_motion_mean_abs: float


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _save_wav(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.astype(np.int16).tobytes())


def _open_writer(path: Path, size: tuple[int, int], fps: int) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, float(fps), size)
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open video writer for {path}")
    return writer


def _put_label(img: np.ndarray, text: str, org: tuple[int, int], scale: float = 0.65) -> None:
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def _make_crop_panel(
    base_crop: np.ndarray,
    pred_crop: np.ndarray,
    comp_crop: np.ndarray,
    frame_idx: int,
    diff_pred: float,
    diff_comp: float,
    feature_delta: float,
) -> np.ndarray:
    tile_h = 256
    tile_w = 256
    header_h = 40
    canvas = np.zeros((header_h + tile_h, tile_w * 3, 3), dtype=np.uint8)
    canvas[:] = (20, 20, 20)
    canvas[header_h:, 0:tile_w] = cv2.resize(base_crop, (tile_w, tile_h), interpolation=cv2.INTER_LINEAR)
    canvas[header_h:, tile_w:tile_w * 2] = cv2.resize(pred_crop, (tile_w, tile_h), interpolation=cv2.INTER_LINEAR)
    canvas[header_h:, tile_w * 2:tile_w * 3] = cv2.resize(comp_crop, (tile_w, tile_h), interpolation=cv2.INTER_LINEAR)
    _put_label(canvas, f"base frame #{frame_idx}", (12, 26))
    _put_label(canvas, "prediction", (tile_w + 12, 26))
    _put_label(canvas, "composed crop", (tile_w * 2 + 12, 26))
    _put_label(canvas, f"pred={diff_pred:.2f}", (12, header_h + tile_h - 10), scale=0.55)
    _put_label(canvas, f"comp={diff_comp:.2f}", (tile_w + 12, header_h + tile_h - 10), scale=0.55)
    _put_label(canvas, f"feat-delta={feature_delta:.2f}", (tile_w * 2 + 12, header_h + tile_h - 10), scale=0.55)
    return canvas


def _draw_series_plot(
    values: list[float],
    path: Path,
    *,
    title: str,
    color: tuple[int, int, int],
    height: int = 480,
    width: int = 1280,
) -> None:
    canvas = np.full((height, width, 3), 245, dtype=np.uint8)
    left = 80
    right = 40
    top = 60
    bottom = 60
    plot_w = width - left - right
    plot_h = height - top - bottom
    cv2.rectangle(canvas, (left, top), (left + plot_w, top + plot_h), (210, 210, 210), 1)
    _put_label(canvas, title, (left, 36), scale=0.8)

    if not values:
        _put_label(canvas, "no data", (left + 20, top + 40))
        cv2.imwrite(str(path), canvas)
        return

    vmax = max(values)
    vmin = min(values)
    if abs(vmax - vmin) < 1e-6:
        vmax = vmin + 1e-6

    for i in range(6):
        y = top + int(plot_h * i / 5)
        cv2.line(canvas, (left, y), (left + plot_w, y), (230, 230, 230), 1)
        label_v = vmax - (vmax - vmin) * i / 5
        _put_label(canvas, f"{label_v:.2f}", (12, y + 5), scale=0.45)

    pts: list[tuple[int, int]] = []
    denom = max(1, len(values) - 1)
    for idx, value in enumerate(values):
        x = left + int(plot_w * idx / denom)
        ratio = (value - vmin) / (vmax - vmin)
        y = top + plot_h - int(ratio * plot_h)
        pts.append((x, y))
    for p1, p2 in zip(pts, pts[1:]):
        cv2.line(canvas, p1, p2, color, 2, cv2.LINE_AA)

    _put_label(canvas, f"frames={len(values)} min={vmin:.2f} max={vmax:.2f}", (left, height - 18), scale=0.55)
    cv2.imwrite(str(path), canvas)


def _normalize_series(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32)
    if arr.size == 0:
        return arr
    vmin = float(arr.min())
    vmax = float(arr.max())
    if abs(vmax - vmin) < 1e-6:
        return np.zeros_like(arr)
    return (arr - vmin) / (vmax - vmin)


def _draw_correlation_explainer(
    feature_values: list[float],
    motion_values: list[float],
    path: Path,
    *,
    title: str = "Feature vs Mouth Motion Alignment",
    height: int = 560,
    width: int = 1280,
) -> dict[str, float | int]:
    canvas = np.full((height, width, 3), 248, dtype=np.uint8)
    left = 90
    right = 40
    top = 90
    bottom = 85
    plot_w = width - left - right
    plot_h = height - top - bottom
    cv2.rectangle(canvas, (left, top), (left + plot_w, top + plot_h), (210, 210, 210), 1)
    _put_label(canvas, title, (left, 40), scale=0.9)

    feat = np.asarray(feature_values, dtype=np.float32)
    motion = np.asarray(motion_values, dtype=np.float32)
    n = min(feat.size, motion.size)
    if n == 0:
        _put_label(canvas, "no data", (left + 20, top + 40))
        cv2.imwrite(str(path), canvas)
        return {"corr": 0.0, "feature_peak_frame": -1, "motion_peak_frame": -1}

    feat = feat[:n]
    motion = motion[:n]
    feat_norm = _normalize_series(feat.tolist())
    motion_norm = _normalize_series(motion.tolist())

    if float(feat.std()) > 0.0 and float(motion.std()) > 0.0:
        corr = float(np.corrcoef(feat, motion)[0, 1])
    else:
        corr = 0.0

    for i in range(6):
        y = top + int(plot_h * i / 5)
        cv2.line(canvas, (left, y), (left + plot_w, y), (230, 230, 230), 1)
        label_v = 1.0 - i / 5
        _put_label(canvas, f"{label_v:.1f}", (30, y + 5), scale=0.45)

    denom = max(1, n - 1)
    feat_pts: list[tuple[int, int]] = []
    motion_pts: list[tuple[int, int]] = []
    for idx in range(n):
        x = left + int(plot_w * idx / denom)
        yf = top + plot_h - int(float(feat_norm[idx]) * plot_h)
        ym = top + plot_h - int(float(motion_norm[idx]) * plot_h)
        feat_pts.append((x, yf))
        motion_pts.append((x, ym))

    for p1, p2 in zip(feat_pts, feat_pts[1:]):
        cv2.line(canvas, p1, p2, (50, 90, 220), 2, cv2.LINE_AA)
    for p1, p2 in zip(motion_pts, motion_pts[1:]):
        cv2.line(canvas, p1, p2, (50, 160, 70), 2, cv2.LINE_AA)

    feature_peak_idx = int(np.argmax(feat))
    motion_peak_idx = int(np.argmax(motion))
    fp = feat_pts[feature_peak_idx]
    mp = motion_pts[motion_peak_idx]
    cv2.circle(canvas, fp, 7, (50, 90, 220), -1, cv2.LINE_AA)
    cv2.circle(canvas, mp, 7, (50, 160, 70), -1, cv2.LINE_AA)
    _put_label(canvas, f"feature peak f={feature_peak_idx}", (fp[0] + 12, max(top + 20, fp[1] - 12)), scale=0.5)
    _put_label(canvas, f"motion peak f={motion_peak_idx}", (mp[0] + 12, min(top + plot_h - 10, mp[1] + 18)), scale=0.5)

    legend_y = height - 45
    cv2.line(canvas, (left, legend_y), (left + 36, legend_y), (50, 90, 220), 3, cv2.LINE_AA)
    _put_label(canvas, "normalized feature delta", (left + 44, legend_y + 6), scale=0.55)
    cv2.line(canvas, (left + 360, legend_y), (left + 396, legend_y), (50, 160, 70), 3, cv2.LINE_AA)
    _put_label(canvas, "normalized mouth motion", (left + 404, legend_y + 6), scale=0.55)

    if corr >= 0.5:
        verdict = "strong alignment"
    elif corr >= 0.2:
        verdict = "moderate alignment"
    elif corr > -0.2:
        verdict = "weak alignment"
    else:
        verdict = "inverse/poor alignment"
    _put_label(canvas, f"corr={corr:.3f}  |  verdict: {verdict}", (left, 68), scale=0.65)
    _put_label(
        canvas,
        "If blue peaks but green stays flat, audio features are changing but lip motion is not following.",
        (left, height - 16),
        scale=0.5,
    )

    cv2.imwrite(str(path), canvas)
    return {
        "corr": corr,
        "feature_peak_frame": feature_peak_idx,
        "motion_peak_frame": motion_peak_idx,
    }


def _mux_audio(video_path: Path, wav_path: Path, out_path: Path, ffmpeg_bin: str) -> None:
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(wav_path),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _write_metrics_csv(path: Path, metrics: list[FrameMetric]) -> None:
    if not metrics:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(metrics[0]).keys()))
        writer.writeheader()
        for metric in metrics:
            writer.writerow(asdict(metric))


def _write_summary_json(
    path: Path,
    metrics: list[FrameMetric],
    crop_wh: tuple[int, int],
    *,
    mode: str,
    chunk_ms: float,
    correlation: dict[str, float | int] | None = None,
) -> None:
    feature_deltas = [m.feature_delta_l2 for m in metrics]
    feature_ma = [m.feature_delta_mean_abs for m in metrics]
    pred_motion = [m.pred_motion_mean_abs for m in metrics]
    comp_motion = [m.comp_motion_mean_abs for m in metrics]
    summary = {
        "mode": mode,
        "chunk_ms": chunk_ms,
        "frames": len(metrics),
        "crop_width": crop_wh[0],
        "crop_height": crop_wh[1],
        "feature_delta_l2_mean": float(np.mean(feature_deltas)) if feature_deltas else 0.0,
        "feature_delta_l2_max": float(np.max(feature_deltas)) if feature_deltas else 0.0,
        "feature_delta_l2_min": float(np.min(feature_deltas)) if feature_deltas else 0.0,
        "feature_delta_mean_abs_mean": float(np.mean(feature_ma)) if feature_ma else 0.0,
        "pred_motion_mean_abs_mean": float(np.mean(pred_motion)) if pred_motion else 0.0,
        "pred_motion_mean_abs_max": float(np.max(pred_motion)) if pred_motion else 0.0,
        "comp_motion_mean_abs_mean": float(np.mean(comp_motion)) if comp_motion else 0.0,
        "comp_motion_mean_abs_max": float(np.max(comp_motion)) if comp_motion else 0.0,
        "feature_delta_zero_like_frames": int(sum(v < 1e-3 for v in feature_deltas)),
    }
    if correlation is not None:
        summary.update(correlation)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


async def _synthesize_chunks(args: argparse.Namespace) -> list[Any]:
    if args.tts_provider == "edge":
        tts = EdgeTTSAdapter(default_voice=args.voice, sample_rate=16000, chunk_ms=args.chunk_ms)
    elif args.tts_provider == "xtts":
        if not args.xtts_reference_audio:
            raise ValueError("--xtts-reference-audio is required when --tts-provider xtts")
        tts = CoquiXTTSAdapter(
            model_name=args.xtts_model_name,
            language=args.xtts_language,
            reference_audio=Path(args.xtts_reference_audio),
            sample_rate=16000,
            chunk_ms=args.chunk_ms,
            device=args.xtts_device,
            cache_dir=ROOT / "temp" / "xtts_cache",
            ffmpeg_bin=args.ffmpeg_bin,
        )
    else:
        raise ValueError(f"unsupported tts provider: {args.tts_provider}")

    chunks = []
    voice = args.voice if args.tts_provider == "edge" else None
    async for chunk in tts.synthesize_stream(args.text, voice=voice):
        chunks.append(chunk)
    return chunks


def _build_full_utterance_chunk(chunks: list[Any]) -> AudioChunk:
    if not chunks:
        raise ValueError("cannot build utterance chunk from empty chunk list")
    pcm = np.concatenate([c.data for c in chunks]).astype(np.int16)
    sr = int(chunks[0].sample_rate)
    duration_ms = 1000.0 * len(pcm) / sr
    return AudioChunk(data=pcm, sample_rate=sr, duration_ms=duration_ms)


def _resolve_avatar_path(avatar: str) -> Path:
    avatar_path = Path(avatar).expanduser()
    if avatar_path.is_dir():
        return avatar_path.resolve()
    candidate = ROOT / "examples" / "avatars" / avatar
    if candidate.is_dir():
        return candidate.resolve()
    raise FileNotFoundError(f"Avatar not found: {avatar}")


async def _run_debug(args: argparse.Namespace) -> Path:
    os.environ["OPENTALKING_MODELS_DIR"] = str((ROOT / "models").resolve())
    os.environ["OPENTALKING_AVATARS_DIR"] = str((ROOT / "examples/avatars").resolve())
    os.environ["OPENTALKING_TORCH_DEVICE"] = args.device
    if args.cuda_visible_devices:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.cuda_visible_devices

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_dir = ROOT / "debug" / f"musetalk-offline-{stamp}"
    _ensure_dir(out_dir)

    print(f"[1/6] synthesizing TTS provider={args.tts_provider} text={args.text}", flush=True)
    chunks = await _synthesize_chunks(args)
    if not chunks:
        raise RuntimeError("TTS produced no chunks")
    pcm = np.concatenate([c.data for c in chunks]).astype(np.int16)
    wav_path = out_dir / "tts.wav"
    _save_wav(wav_path, pcm, 16000)
    total_ms = sum(c.duration_ms for c in chunks)
    print(f"  chunks={len(chunks)} total_ms={total_ms:.1f} mode={args.mode}", flush=True)

    render_inputs: list[AudioChunk]
    if args.mode == "full":
        render_inputs = [_build_full_utterance_chunk(chunks)]
    else:
        render_inputs = chunks

    print(f"[2/6] loading MuseTalk model avatar={args.avatar}", flush=True)
    adapter = MuseTalkAdapter()
    adapter.load_model(args.device)
    adapter.warmup()
    avatar_path = _resolve_avatar_path(args.avatar)
    avatar_state = adapter.load_avatar(str(avatar_path))
    reset_avatar_speech_state(avatar_state)
    fps = int(avatar_state.manifest.fps)
    full_h, full_w = avatar_state.frames[0].shape[:2]
    _, sample_ci = crop_face_region(avatar_state.frames[0])
    crop_wh = (sample_ci.x2 - sample_ci.x1, sample_ci.y2 - sample_ci.y1)
    print(f"  fps={fps} crop_wh={crop_wh}", flush=True)

    composed_silent = out_dir / "composed_silent.mp4"
    crops_silent = out_dir / "crops_silent.mp4"
    full_writer = _open_writer(composed_silent, (full_w, full_h), fps)
    crop_writer = _open_writer(crops_silent, (256 * 3, 296), fps)

    print("[3/6] running MuseTalk inference and collecting frame metrics", flush=True)
    metrics: list[FrameMetric] = []
    frame_idx = 0
    speech_frame_idx = 0
    best_panel = None
    best_motion = -1.0

    for chunk_idx, chunk in enumerate(render_inputs):
        rendered = prepare_rendered_chunk_sync(
            adapter,
            avatar_state,
            chunk,
            frame_index_start=frame_idx,
            speech_frame_index_start=speech_frame_idx,
            streaming=args.mode == "chunked",
            infer_batch_frames=(
                max(1, int(args.infer_batch_frames))
                if args.mode == "full"
                else None
            ),
        )
        features = rendered.features
        feature_vectors = getattr(features, "vector", None)
        if isinstance(feature_vectors, np.ndarray):
            feature_vectors = np.asarray(feature_vectors, dtype=np.float32)
        else:
            feature_vectors = np.zeros((0,), dtype=np.float32)
        preds = rendered.predictions

        print(
            f"  chunk {chunk_idx + 1:02d}/{len(render_inputs)} dur={chunk.duration_ms:.0f}ms "
            f"frames={len(preds)} feat_shape={tuple(feature_vectors.shape)} start_frame={frame_idx}",
            flush=True,
        )
        crop_infos = avatar_state.extra.get("crop_infos")
        prev_feat: np.ndarray | None = None

        for local_frame_idx, pred in enumerate(preds):
            current_frame_idx = frame_idx + local_frame_idx
            feat_index = min(local_frame_idx, max(0, len(feature_vectors) - 1))
            feat = np.asarray(feature_vectors[feat_index]).reshape(-1) if feature_vectors.size else np.zeros((1,), dtype=np.float32)
            if prev_feat is None:
                feature_delta_l2 = 0.0
                feature_delta_mean_abs = 0.0
            else:
                delta = feat - prev_feat
                feature_delta_l2 = float(np.linalg.norm(delta))
                feature_delta_mean_abs = float(np.mean(np.abs(delta)))
            prev_feat = feat

            composed = rendered.frames[local_frame_idx].data
            full_writer.write(composed)

            pred_motion = 0.0
            comp_motion = 0.0
            if crop_infos is not None and isinstance(pred, np.ndarray):
                ci = crop_infos[current_frame_idx % len(crop_infos)]
                base = avatar_state.frames[current_frame_idx % len(avatar_state.frames)]
                base_crop = cv2.resize(base[ci.y1 : ci.y2, ci.x1 : ci.x2], (256, 256), interpolation=cv2.INTER_LINEAR)
                comp_crop = cv2.resize(composed[ci.y1 : ci.y2, ci.x1 : ci.x2], (256, 256), interpolation=cv2.INTER_LINEAR)
                pred_crop = cv2.resize(pred, (256, 256), interpolation=cv2.INTER_LINEAR)
                pred_motion = float(np.mean(np.abs(pred_crop.astype(np.float32) - base_crop.astype(np.float32))))
                comp_motion = float(np.mean(np.abs(comp_crop.astype(np.float32) - base_crop.astype(np.float32))))
                panel = _make_crop_panel(
                    base_crop,
                    pred_crop,
                    comp_crop,
                    current_frame_idx,
                    pred_motion,
                    comp_motion,
                    feature_delta_l2,
                )
                crop_writer.write(panel)
                if comp_motion > best_motion:
                    best_motion = comp_motion
                    best_panel = panel.copy()
            else:
                fallback_crop = cv2.resize(composed, (256, 256), interpolation=cv2.INTER_LINEAR)
                panel = _make_crop_panel(
                    fallback_crop,
                    fallback_crop,
                    fallback_crop,
                    current_frame_idx,
                    0.0,
                    0.0,
                    feature_delta_l2,
                )
                crop_writer.write(panel)

            metrics.append(
                FrameMetric(
                    frame_idx=current_frame_idx,
                    chunk_idx=chunk_idx,
                    local_frame_idx=local_frame_idx,
                    feature_norm=float(np.linalg.norm(feat)),
                    feature_delta_l2=feature_delta_l2,
                    feature_delta_mean_abs=feature_delta_mean_abs,
                    pred_motion_mean_abs=pred_motion,
                    comp_motion_mean_abs=comp_motion,
                )
            )
        frame_idx = rendered.next_frame_idx
        speech_frame_idx += len(preds)

    full_writer.release()
    crop_writer.release()

    print("[4/6] writing debug metrics", flush=True)
    csv_path = out_dir / "feature_deltas.csv"
    summary_path = out_dir / "summary.json"
    _write_metrics_csv(csv_path, metrics)

    feature_plot = out_dir / "feature_delta_plot.png"
    motion_plot = out_dir / "mouth_motion_plot.png"
    correlation_plot = out_dir / "correlation_explainer.png"
    feature_series = [m.feature_delta_l2 for m in metrics]
    motion_series = [m.comp_motion_mean_abs for m in metrics]
    correlation = _draw_correlation_explainer(feature_series, motion_series, correlation_plot)
    _draw_series_plot(
        feature_series,
        feature_plot,
        title="Per-frame audio feature delta (L2)",
        color=(40, 90, 220),
    )
    _draw_series_plot(
        motion_series,
        motion_plot,
        title="Per-frame composed mouth motion (mean abs diff)",
        color=(50, 160, 70),
    )
    _write_summary_json(
        summary_path,
        metrics,
        crop_wh,
        mode=args.mode,
        chunk_ms=args.chunk_ms,
        correlation=correlation,
    )

    if best_panel is not None:
        cv2.imwrite(str(out_dir / "max_motion_panel.png"), best_panel)

    print("[5/6] muxing audio into debug videos", flush=True)
    _mux_audio(composed_silent, wav_path, out_dir / "composed_with_audio.mp4", args.ffmpeg_bin)
    _mux_audio(crops_silent, wav_path, out_dir / "crops_with_audio.mp4", args.ffmpeg_bin)

    print("[6/6] done", flush=True)
    print(f"  out_dir={out_dir}", flush=True)
    print(f"  summary={summary_path}", flush=True)
    print(f"  csv={csv_path}", flush=True)
    print(f"  feature_plot={feature_plot}", flush=True)
    print(f"  motion_plot={motion_plot}", flush=True)
    print(f"  correlation_plot={correlation_plot}", flush=True)
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline MuseTalk debug runner")
    parser.add_argument(
        "--text",
        default="你好，欢迎来到 OpenTalking。现在我们正在测试 MuseTalk 的口型同步效果，请连续说几句稍长一点的话。",
    )
    parser.add_argument("--avatar", default="demo-musetalk")
    parser.add_argument("--tts-provider", choices=("edge", "xtts"), default="edge")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--xtts-model-name", default="./models/XTTS-v2")
    parser.add_argument("--xtts-reference-audio", default="")
    parser.add_argument("--xtts-language", default="zh-cn")
    parser.add_argument("--xtts-device", default="auto")
    parser.add_argument("--chunk-ms", type=float, default=320.0)
    parser.add_argument("--mode", choices=("chunked", "full"), default="chunked")
    parser.add_argument("--infer-batch-frames", type=int, default=32)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--cuda-visible-devices", default=os.environ.get("CUDA_VISIBLE_DEVICES", ""))
    args = parser.parse_args()

    out_dir = asyncio.run(_run_debug(args))
    print(out_dir)


if __name__ == "__main__":
    main()
