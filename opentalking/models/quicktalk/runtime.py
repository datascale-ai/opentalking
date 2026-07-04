#!/usr/bin/env python3
"""V3 realtime-oriented worker built on the V2 model.

The worker keeps the V2 model and template video resident, then emits frames as
soon as each mouth patch is generated. The CLI in this file uses a wav file to
simulate a streaming TTS source; a production integration should feed PCM/audio
features incrementally and consume frames from ``generate_frames_from_reps``.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import cv2
import kornia
import numpy as np
import torch
import torch.nn.functional as F
from kornia.filters import gaussian_blur2d
from kornia.geometry.transform import invert_affine_transform, warp_affine

from .runtime_v2 import FaceDetection, QuickTalkRebuild, ensure_ffmpeg, maybe_mkdir, run_cmd


@dataclass
class RealtimeStats:
    frames: int = 0
    first_frame_seconds: float | None = None
    generate_seconds: float = 0.0
    audio_feature_seconds: float = 0.0
    mux_seconds: float = 0.0

    @property
    def fps(self) -> float:
        if self.generate_seconds <= 0:
            return 0.0
        return self.frames / self.generate_seconds


@dataclass
class RealtimeV3SessionState:
    """Per-session mutable state for ``RealtimeV3Worker``.

    Allows multiple sessions to share the same expensive Worker (template
    frames, restore contexts, ONNX/HuBERT) without contaminating each other's
    LSTM hidden states or template cycle position.
    """

    frame_index: int = 0
    hn: np.ndarray | None = None
    cn: np.ndarray | None = None

    def reset(self) -> None:
        self.frame_index = 0
        if self.hn is not None:
            self.hn.fill(0)
        if self.cn is not None:
            self.cn.fill(0)


@dataclass
class FastRestoreContext:
    frame: np.ndarray
    face: np.ndarray
    face_input: np.ndarray
    coords: list[int]
    affine: np.ndarray
    roi: tuple[int, int, int, int]
    inv_affine_roi: torch.Tensor
    frame_roi_t: torch.Tensor
    hard_mask_roi_3d: torch.Tensor
    soft_mask_roi_3d: torch.Tensor


@dataclass(frozen=True)
class FaceTrack:
    face_id: str
    order: int


@dataclass(frozen=True)
class MultiFaceSegment:
    speaker_id: str
    start_ms: int
    end_ms: int
    audio: str | Path | None = None
    reps: Sequence[np.ndarray] | None = None


@dataclass
class MultiFaceSessionState:
    frame_index: int
    face_states: dict[str, RealtimeV3SessionState]

    def reset(self) -> None:
        self.frame_index = 0
        for state in self.face_states.values():
            state.reset()


@dataclass(frozen=True)
class MouthHoldState:
    face_id: str
    frame_index: int
    hold_frames: int
    roi: tuple[int, int, int, int]
    patch: np.ndarray
    weight: np.ndarray


def _segment_from_mapping(raw: Mapping[str, Any]) -> MultiFaceSegment:
    return MultiFaceSegment(
        speaker_id=str(raw.get("speaker_id") or "").strip(),
        start_ms=int(raw.get("start_ms") or 0),
        end_ms=int(raw.get("end_ms") or 0),
        audio=raw.get("audio"),
    )


def validate_multiface_script(script: Mapping[str, Any]) -> tuple[dict[str, str], list[MultiFaceSegment]]:
    raw_speaker_faces = script.get("speaker_faces")
    if not isinstance(raw_speaker_faces, Mapping) or not raw_speaker_faces:
        raise ValueError("speaker_faces must be a non-empty mapping")
    speaker_faces = {
        str(speaker_id).strip(): str(face_id).strip()
        for speaker_id, face_id in raw_speaker_faces.items()
        if str(speaker_id).strip() and str(face_id).strip()
    }
    if not speaker_faces:
        raise ValueError("speaker_faces must contain at least one speaker")

    raw_segments = script.get("segments")
    if not isinstance(raw_segments, Sequence) or isinstance(raw_segments, (str, bytes)):
        raise ValueError("segments must be a list")
    segments = [_segment_from_mapping(item) for item in raw_segments if isinstance(item, Mapping)]
    if len(segments) != len(raw_segments):
        raise ValueError("segments must contain objects")
    segments = sorted(segments, key=lambda item: (item.start_ms, item.end_ms))

    previous_end = -1
    for segment in segments:
        if segment.speaker_id not in speaker_faces:
            raise ValueError(f"unknown speaker_id: {segment.speaker_id}")
        if segment.end_ms <= segment.start_ms:
            raise ValueError(f"invalid segment duration for speaker_id: {segment.speaker_id}")
        if previous_end > segment.start_ms:
            raise ValueError("overlapping segments are not supported")
        previous_end = segment.end_ms
    return speaker_faces, segments


def _face_center_x(detection: Any) -> float:
    center_x = getattr(detection, "center_x", None)
    if center_x is not None:
        return float(center_x)
    bbox = np.asarray(getattr(detection, "bbox"), dtype=np.float32)
    return float((bbox[0] + bbox[2]) / 2.0)


def assign_face_ids_by_x(detections: Sequence[FaceDetection]) -> list[tuple[str, FaceDetection]]:
    ordered = sorted(detections, key=_face_center_x)
    if len(ordered) == 2:
        names = ["left", "right"]
    elif len(ordered) == 3:
        names = ["left", "center", "right"]
    else:
        names = [f"face_{idx}" for idx in range(len(ordered))]
    return list(zip(names, ordered))


class RealtimeV3Worker:
    def __init__(
        self,
        asset_root: Path,
        template_video: Path,
        face_cache_dir: Path | None = None,
        face_cache_file: Path | None = None,
        batch_size: int = 1,
        device: str = "cuda:0",
        output_transform: str = "bgr",
        scale_h: float = 1.6,
        scale_w: float = 3.6,
        resolution: int = 256,
        max_template_seconds: float | None = None,
        neck_fade_start: float | None = None,
        neck_fade_end: float | None = None,
        hubert_device: str | None = None,
        model_backend: str = "auto",
    ) -> None:
        self.template_video = template_video
        self.face_cache_file = face_cache_file
        if (neck_fade_start is None) != (neck_fade_end is None):
            raise ValueError("neck_fade_start and neck_fade_end must be set together")
        if neck_fade_start is not None and neck_fade_end is not None and not 0.0 <= neck_fade_start < neck_fade_end <= 1.0:
            raise ValueError("neck_fade_start/end must satisfy 0 <= start < end <= 1")
        self.neck_fade_start = neck_fade_start
        self.neck_fade_end = neck_fade_end
        self.v2 = QuickTalkRebuild(
            asset_root=asset_root,
            batch_size=batch_size,
            scale_h=scale_h,
            scale_w=scale_w,
            resolution=resolution,
            face_cache_dir=face_cache_dir,
            device=device,
            output_transform=output_transform,
            hubert_device=hubert_device,
            model_backend=model_backend,
        )
        self.input_names = self.v2.model_backend.input_names
        self.frames, self.fps = self._load_template_frames(template_video, max_template_seconds)
        if not self.frames:
            raise RuntimeError(f"No template frames read from {template_video}")
        self.face_det_results = self._load_or_build_template_cache(max_template_seconds)
        self.restore_contexts = self._build_fast_restore_contexts()
        self.frame_index = 0
        self.hn = np.zeros((2, 1, 576), dtype=np.float32)
        self.cn = np.zeros((2, 1, 576), dtype=np.float32)
        self.warmup()

    def make_state(self) -> RealtimeV3SessionState:
        """Allocate fresh per-session state (LSTM hidden + template cycle)."""
        return RealtimeV3SessionState(
            frame_index=0,
            hn=np.zeros((2, 1, 576), dtype=np.float32),
            cn=np.zeros((2, 1, 576), dtype=np.float32),
        )

    def reset_state(self) -> None:
        """Reset the worker's *internal default* state (CLI/offline paths only)."""
        self.frame_index = 0
        self.hn.fill(0)
        self.cn.fill(0)

    def warmup(self) -> None:
        # Use a fresh local state so we don't perturb the worker's default state.
        local_state = self.make_state()
        dummy_rep = np.zeros((10, 1024), dtype=np.float32)
        for _ in self.generate_frames_from_reps([dummy_rep], state=local_state):
            pass

    def _load_template_frames(self, video_path: Path, max_seconds: float | None) -> tuple[list[np.ndarray], float]:
        with tempfile.TemporaryDirectory(prefix="openstudio_v3_template_") as tmpdir:
            workdir = Path(tmpdir)
            video_25 = self._ensure_25fps(video_path, workdir, max_seconds)
            return self.v2.read_frames(video_25, max_seconds=max_seconds)

    def _ensure_25fps(self, video_path: Path, workdir: Path, max_seconds: float | None) -> Path:
        cap = cv2.VideoCapture(str(video_path))
        src_fps = float(cap.get(cv2.CAP_PROP_FPS))
        cap.release()
        if src_fps <= 0:
            raise RuntimeError(f"Invalid FPS from video: {video_path}")
        if abs(src_fps - 25.0) <= 1e-3:
            return video_path
        out = workdir / "template_25fps.mp4"
        cmd = [
            ensure_ffmpeg(),
            "-y",
            "-i",
            str(video_path),
            "-r",
            "25",
        ]
        if max_seconds is not None:
            cmd += ["-t", str(max_seconds)]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", str(out)]
        run_cmd(cmd)
        return out

    def _load_or_build_template_cache(self, max_template_seconds: float | None) -> Sequence[tuple[np.ndarray, list[int], np.ndarray]]:
        if self.face_cache_file is not None:
            cached = self.v2.load_face_cache(self.face_cache_file)
            if cached is not None and len(cached) == len(self.frames):
                print(f"v3_template_cache=asset_hit frames={len(cached)} path={self.face_cache_file}", flush=True)
                return cached
            print(f"v3_template_cache=asset_miss path={self.face_cache_file}", flush=True)

        read_limit = max_template_seconds if max_template_seconds is not None else len(self.frames) / self.fps
        cache_path = self.v2.face_cache_path(self.template_video, len(self.frames), self.fps, read_limit)
        cached = self.v2.load_face_cache(cache_path) if cache_path is not None else None
        if cached is not None and len(cached) == len(self.frames):
            print(f"v3_template_cache=hit frames={len(cached)} path={cache_path}", flush=True)
            return cached
        start = time.perf_counter()
        results = self.v2.face_detect_frames(self.frames)
        if cache_path is not None:
            self.v2.save_face_cache(cache_path, results)
        print(f"v3_template_cache=miss face_detect_seconds={time.perf_counter() - start:.3f} frames={len(results)}", flush=True)
        return results

    def _build_fast_restore_context(
        self,
        frame: np.ndarray,
        face: np.ndarray,
        coords: list[int],
        affine: np.ndarray,
    ) -> FastRestoreContext:
        restorer = self.v2.image_processor.restorer
        device = self.v2.device
        restore_dtype = restorer.dtype
        output_dtype = self.v2.dtype
        h, w = frame.shape[:2]
        face_rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        ref_pixel_values, masked_pixel_values, masks = self.v2.image_processor.prepare_masks_and_masked_images(
            np.asarray([face_rgb]),
            affine_transform=False,
        )
        face_input = torch.cat((masks, masked_pixel_values, ref_pixel_values), dim=1).numpy().astype(np.float32)
        affine_t = torch.from_numpy(affine).to(device=device, dtype=restore_dtype).unsqueeze(0)
        inv_affine = invert_affine_transform(affine_t)
        inv_mask = warp_affine(restorer.mask, inv_affine, (h, w), padding_mode="zeros")
        inv_mask_erosion = kornia.morphology.erosion(
            inv_mask,
            torch.ones(
                (int(2 * restorer.upscale_factor), int(2 * restorer.upscale_factor)),
                device=device,
                dtype=restore_dtype,
            ),
        )
        mask_np = inv_mask_erosion.squeeze().detach().cpu().numpy().astype(np.float32)
        ys, xs = np.where(mask_np > 0.001)
        if len(xs) == 0 or len(ys) == 0:
            x0, y0, x1, y1 = 0, 0, w, h
        else:
            pad = 16
            x0 = max(int(xs.min()) - pad, 0)
            x1 = min(int(xs.max()) + pad + 1, w)
            y0 = max(int(ys.min()) - pad, 0)
            y1 = min(int(ys.max()) + pad + 1, h)

        total_face_area = int(torch.sum(inv_mask_erosion.float()).item())
        w_edge = max(int(np.sqrt(max(total_face_area, 1))) // 20, 1)
        erosion_radius = max(w_edge * 2, 1)
        kernel = np.ones((int(erosion_radius * self.v2.scale_h), int(erosion_radius * self.v2.scale_w)), np.uint8)
        inv_mask_center = cv2.erode(mask_np, kernel)
        inv_mask_center_t = torch.from_numpy(inv_mask_center).to(device=device, dtype=restore_dtype)[None, None, ...]
        blur_size = max(w_edge * 2 + 1, 3)
        sigma = 0.3 * ((blur_size - 1) * 0.5 - 1) + 0.8
        inv_soft_mask = gaussian_blur2d(inv_mask_center_t, (blur_size, blur_size), (sigma, sigma)).squeeze(0)
        hard_mask_roi_3d = inv_mask_erosion.squeeze(0)[:, y0:y1, x0:x1].expand(3, y1 - y0, x1 - x0).contiguous()
        soft_mask_roi_3d = inv_soft_mask[:, y0:y1, x0:x1].expand(3, y1 - y0, x1 - x0).contiguous()
        soft_mask_roi_3d = self._apply_neck_fade(soft_mask_roi_3d)

        inv_affine_roi = inv_affine.clone()
        inv_affine_roi[:, 0, 2] -= x0
        inv_affine_roi[:, 1, 2] -= y0
        frame_roi_t = torch.from_numpy(frame[y0:y1, x0:x1]).to(device=device, dtype=output_dtype).permute(2, 0, 1).contiguous()
        return FastRestoreContext(
            frame=frame,
            face=face,
            face_input=face_input,
            coords=coords,
            affine=affine,
            roi=(x0, y0, x1, y1),
            inv_affine_roi=inv_affine_roi.to(dtype=output_dtype),
            frame_roi_t=frame_roi_t,
            hard_mask_roi_3d=hard_mask_roi_3d.to(dtype=output_dtype),
            soft_mask_roi_3d=soft_mask_roi_3d.to(dtype=output_dtype),
        )

    def _build_fast_restore_contexts(self) -> list[FastRestoreContext]:
        start = time.perf_counter()
        contexts: list[FastRestoreContext] = []
        for frame, (face, coords, affine) in zip(self.frames, self.face_det_results):
            contexts.append(
                self._build_fast_restore_context(
                    frame=frame,
                    face=face,
                    coords=coords,
                    affine=affine,
                )
            )
        print(f"v3_restore_context_seconds={time.perf_counter() - start:.3f} frames={len(contexts)}", flush=True)
        return contexts

    def _apply_neck_fade(self, soft_mask_roi_3d: torch.Tensor) -> torch.Tensor:
        if self.neck_fade_start is None or self.neck_fade_end is None:
            return soft_mask_roi_3d
        roi_h = soft_mask_roi_3d.shape[1]
        fade_start = min(max(int(roi_h * self.neck_fade_start), 0), roi_h - 1)
        fade_end = min(max(int(roi_h * self.neck_fade_end), fade_start + 1), roi_h)
        weights = torch.ones((roi_h,), device=soft_mask_roi_3d.device, dtype=soft_mask_roi_3d.dtype)
        weights[fade_start:fade_end] = torch.linspace(
            1.0,
            0.0,
            fade_end - fade_start,
            device=soft_mask_roi_3d.device,
            dtype=soft_mask_roi_3d.dtype,
        )
        weights[fade_end:] = 0.0
        return soft_mask_roi_3d * weights[None, :, None]

    def prepare_wav_features(self, audio_path: Path) -> tuple[list[np.ndarray], float]:
        start = time.perf_counter()
        repst = self.v2.extract_representations(audio_path)
        with wave.open(str(audio_path), "rb") as wav:
            audio_duration = float(wav.getnframes()) / float(wav.getframerate())
        n_frames = max(1, int(audio_duration * self.fps))
        reps = self.v2.build_rep_chunks(repst, n_frames, self.fps)
        return reps, time.perf_counter() - start

    def prepare_pcm_features(
        self, pcm: np.ndarray, sample_rate: int
    ) -> tuple[list[np.ndarray], float]:
        """Same as ``prepare_wav_features`` but takes raw PCM, skipping tempfile I/O."""
        start = time.perf_counter()
        repst = self.v2.extract_representations_pcm(pcm, sample_rate)
        sample_count = int(np.asarray(pcm).reshape(-1).shape[0])
        sample_rate = int(sample_rate)
        if sample_rate <= 0:
            raise ValueError(f"Invalid sample_rate: {sample_rate}")
        audio_duration = sample_count / float(sample_rate)
        n_frames = max(1, int(audio_duration * self.fps))
        reps = self.v2.build_rep_chunks(repst, n_frames, self.fps)
        return reps, time.perf_counter() - start

    def _template_item(self, state: RealtimeV3SessionState | None = None) -> FastRestoreContext:
        n = len(self.restore_contexts)
        if state is not None:
            cycle = state.frame_index // n
            offset = state.frame_index % n
            idx = offset if cycle % 2 == 0 else n - 1 - offset
            state.frame_index += 1
        else:
            cycle = self.frame_index // n
            offset = self.frame_index % n
            idx = offset if cycle % 2 == 0 else n - 1 - offset
            self.frame_index += 1
        return self.restore_contexts[idx]

    def fast_restore_img(
        self,
        context: FastRestoreContext,
        patch_t: torch.Tensor,
        base_frame: np.ndarray | None = None,
        paste_weight: torch.Tensor | None = None,
    ) -> np.ndarray:
        x0, y0, x1, y1 = context.roi
        roi_h = y1 - y0
        roi_w = x1 - x0
        restorer = self.v2.image_processor.restorer
        # 调用方已保证 ``patch_t`` 在目标 device + dtype 上，这里不再 ``.to``
        # 触发额外搬运，仅 unsqueeze 一次即可（GPU 操作）。
        face_t = patch_t.unsqueeze(0)
        inv_face = warp_affine(
            face_t,
            context.inv_affine_roi,
            (roi_h, roi_w),
            mode="bilinear",
            padding_mode="fill",
            fill_value=restorer.fill_value,
        ).squeeze(0)
        inv_face = inv_face.clamp(0, 1) * 255.0
        pasted_face = context.hard_mask_roi_3d * inv_face
        output = context.frame.copy() if base_frame is None else base_frame.copy()
        base_roi_t = context.frame_roi_t
        if base_frame is not None:
            base_roi_t = (
                torch.from_numpy(base_frame[y0:y1, x0:x1])
                .to(device=context.soft_mask_roi_3d.device, dtype=context.soft_mask_roi_3d.dtype)
                .permute(2, 0, 1)
                .contiguous()
            )
        soft_mask_roi_3d = context.soft_mask_roi_3d
        if paste_weight is not None:
            paste_weight = paste_weight.to(device=soft_mask_roi_3d.device, dtype=soft_mask_roi_3d.dtype)
            if paste_weight.ndim == 2:
                paste_weight = paste_weight.unsqueeze(0)
            if paste_weight.shape[0] == 1:
                paste_weight = paste_weight.expand_as(soft_mask_roi_3d)
            soft_mask_roi_3d = soft_mask_roi_3d * paste_weight
        roi = soft_mask_roi_3d * pasted_face + (1.0 - soft_mask_roi_3d) * base_roi_t
        output[y0:y1, x0:x1] = roi.permute(1, 2, 0).contiguous().to(dtype=torch.uint8).cpu().numpy()
        return output

    def generate_frames_from_reps(
        self,
        reps: Sequence[np.ndarray],
        state: RealtimeV3SessionState | None = None,
    ) -> Iterator[np.ndarray]:
        with torch.inference_mode():
            for rep in reps:
                context = self._template_item(state)
                rep_input = rep[None, ...].astype(np.float32)
                if state is not None:
                    hn_in, cn_in = state.hn, state.cn
                else:
                    hn_in, cn_in = self.hn, self.cn
                if hn_in is None or cn_in is None:
                    raise RuntimeError("QuickTalk session state is not initialized")
                g, hn_out, cn_out = self.v2.run_model(
                    rep_input.astype(np.float32),
                    context.face_input,
                    hn_in,
                    cn_in,
                )
                if state is not None:
                    state.hn, state.cn = hn_out, cn_out
                else:
                    self.hn, self.cn = hn_out, cn_out
                # ORT 输出在 CPU；只做一次 numpy→torch.cuda 搬运后保持 GPU。
                # 旧代码会再做一次 numpy→torch（fast_restore_img 入口又来一次
                # ``.to(device, dtype)``），这里彻底合并掉。
                g_arr = g.squeeze(0)
                if g_arr.dtype != np.float32:
                    g_arr = g_arr.astype(np.float32)
                patch_t = (
                    torch.from_numpy(g_arr)
                    .to(device=self.v2.device, dtype=self.v2.dtype, non_blocking=True)
                )
                patch_t = self.v2.transform_output_torch(patch_t)
                x1, y1, x2, y2 = context.coords
                patch_t = F.interpolate(
                    patch_t.unsqueeze(0),
                    size=(int(y2 - y1), int(x2 - x1)),
                    mode="bicubic",
                    align_corners=False,
                    antialias=True,
                ).squeeze(0)
                yield self.fast_restore_img(context, patch_t)

    def generate_video_from_wav(
        self,
        audio_path: Path,
        output_path: Path,
        codec: str = "mp4v",
        sink: str = "ffmpeg-pipe",
        video_codec: str = "libx264",
        ffmpeg_preset: str = "veryfast",
        ffmpeg_tune: str | None = "zerolatency",
        crf: int = 18,
    ) -> RealtimeStats:
        if sink == "opencv":
            return self._generate_video_from_wav_opencv(audio_path, output_path, codec, video_codec, ffmpeg_preset, ffmpeg_tune, crf)
        if sink == "ffmpeg-pipe":
            return self._generate_video_from_wav_ffmpeg_pipe(audio_path, output_path, video_codec, ffmpeg_preset, ffmpeg_tune, crf)
        raise ValueError(f"Unsupported sink: {sink}")

    def _generate_video_from_wav_opencv(
        self,
        audio_path: Path,
        output_path: Path,
        codec: str,
        video_codec: str,
        ffmpeg_preset: str,
        ffmpeg_tune: str | None,
        crf: int,
    ) -> RealtimeStats:
        maybe_mkdir(output_path.parent)
        reps, feature_seconds = self.prepare_wav_features(audio_path)
        h, w = self.frames[0].shape[:2]
        stats = RealtimeStats(audio_feature_seconds=feature_seconds)
        with tempfile.TemporaryDirectory(prefix="openstudio_v3_") as tmpdir:
            temp_video = Path(tmpdir) / "realtime_frames.mp4"
            video_writer_fourcc = getattr(cv2, "VideoWriter_fourcc")
            writer = cv2.VideoWriter(str(temp_video), video_writer_fourcc(*codec), self.fps, (w, h))
            if not writer.isOpened():
                raise RuntimeError(f"Failed to open VideoWriter: {temp_video}")
            start = time.perf_counter()
            for frame in self.generate_frames_from_reps(reps):
                if stats.frames == 0:
                    stats.first_frame_seconds = time.perf_counter() - start
                writer.write(frame)
                stats.frames += 1
            writer.release()
            stats.generate_seconds = time.perf_counter() - start

            mux_start = time.perf_counter()
            cmd = [
                ensure_ffmpeg(),
                "-y",
                "-i",
                str(temp_video),
                "-i",
                str(audio_path),
            ]
            cmd += self._ffmpeg_video_encode_args(video_codec, ffmpeg_preset, ffmpeg_tune, crf)
            cmd += ["-c:a", "aac", "-shortest", str(output_path)]
            run_cmd(cmd)
            stats.mux_seconds = time.perf_counter() - mux_start
        return stats

    def _generate_video_from_wav_ffmpeg_pipe(
        self,
        audio_path: Path,
        output_path: Path,
        video_codec: str,
        ffmpeg_preset: str,
        ffmpeg_tune: str | None,
        crf: int,
    ) -> RealtimeStats:
        maybe_mkdir(output_path.parent)
        reps, feature_seconds = self.prepare_wav_features(audio_path)
        h, w = self.frames[0].shape[:2]
        stats = RealtimeStats(audio_feature_seconds=feature_seconds)
        cmd = [
            ensure_ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{w}x{h}",
            "-r",
            f"{self.fps:g}",
            "-i",
            "pipe:0",
            "-i",
            str(audio_path),
        ]
        cmd += self._ffmpeg_video_encode_args(video_codec, ffmpeg_preset, ffmpeg_tune, crf)
        cmd += ["-c:a", "aac", "-shortest", str(output_path)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.stdin is None:
            proc.kill()
            raise RuntimeError("Failed to open ffmpeg stdin pipe")

        start = time.perf_counter()
        try:
            for frame in self.generate_frames_from_reps(reps):
                if stats.frames == 0:
                    stats.first_frame_seconds = time.perf_counter() - start
                proc.stdin.write(np.ascontiguousarray(frame).tobytes())
                stats.frames += 1
        except Exception:
            proc.kill()
            proc.wait()
            raise
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass

        stats.generate_seconds = time.perf_counter() - start
        mux_start = time.perf_counter()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr is not None else ""
        return_code = proc.wait()
        stats.mux_seconds = time.perf_counter() - mux_start
        if return_code != 0:
            raise RuntimeError(f"ffmpeg pipe failed with code {return_code}: {stderr.strip()}")
        return stats

    @staticmethod
    def _ffmpeg_video_encode_args(video_codec: str, ffmpeg_preset: str, ffmpeg_tune: str | None, crf: int) -> list[str]:
        args = ["-c:v", video_codec]
        if video_codec in {"libx264", "libx264rgb"}:
            args += ["-preset", ffmpeg_preset]
            if ffmpeg_tune:
                args += ["-tune", ffmpeg_tune]
            args += ["-crf", str(crf), "-pix_fmt", "yuv420p"]
        elif video_codec == "h264_nvenc":
            args += ["-preset", ffmpeg_preset, "-cq", str(crf), "-pix_fmt", "yuv420p"]
        else:
            args += ["-pix_fmt", "yuv420p"]
        return args


class MultiFaceRealtimeV3Worker(RealtimeV3Worker):
    """Offline multi-face QuickTalk renderer for fixed-template speaker routes."""

    def __init__(
        self,
        asset_root: Path,
        template_video: Path,
        face_cache_dir: Path | None = None,
        batch_size: int = 1,
        device: str = "cuda:0",
        output_transform: str = "bgr",
        scale_h: float = 1.6,
        scale_w: float = 3.6,
        resolution: int = 256,
        max_template_seconds: float | None = None,
        neck_fade_start: float | None = None,
        neck_fade_end: float | None = None,
        hubert_device: str | None = None,
        model_backend: str = "auto",
        min_faces: int = 2,
        paste_strength: float = 1.0,
        mouth_hold_ms: int = 0,
        tail_fade_ms: int = 0,
        tail_fade_region: str = "mouth",
        tail_fade_mouth_start: float = 0.5,
        tail_fade_mouth_ramp: float = 0.18,
        idle_anchor_mode: str = "none",
        idle_anchor_start: float = 0.55,
    ) -> None:
        self.template_video = template_video
        self.face_cache_file = None
        self.paste_strength = min(max(float(paste_strength), 0.0), 1.0)
        self.mouth_hold_ms = max(0, int(mouth_hold_ms))
        self.tail_fade_ms = max(0, int(tail_fade_ms))
        self.tail_fade_region = tail_fade_region.strip().lower() or "mouth"
        if self.tail_fade_region not in {"roi", "mouth"}:
            raise ValueError("tail_fade_region must be one of: roi, mouth")
        self.tail_fade_mouth_start = min(max(float(tail_fade_mouth_start), 0.0), 1.0)
        self.tail_fade_mouth_ramp = min(max(float(tail_fade_mouth_ramp), 0.0), 1.0)
        self.idle_anchor_mode = idle_anchor_mode.strip().lower() or "none"
        if self.idle_anchor_mode not in {"none", "mouth", "face"}:
            raise ValueError("idle_anchor_mode must be one of: none, mouth, face")
        self.idle_anchor_start = min(max(float(idle_anchor_start), 0.0), 1.0)
        if (neck_fade_start is None) != (neck_fade_end is None):
            raise ValueError("neck_fade_start and neck_fade_end must be set together")
        if neck_fade_start is not None and neck_fade_end is not None and not 0.0 <= neck_fade_start < neck_fade_end <= 1.0:
            raise ValueError("neck_fade_start/end must satisfy 0 <= start < end <= 1")
        self.neck_fade_start = neck_fade_start
        self.neck_fade_end = neck_fade_end
        self.v2 = QuickTalkRebuild(
            asset_root=asset_root,
            batch_size=batch_size,
            scale_h=scale_h,
            scale_w=scale_w,
            resolution=resolution,
            face_cache_dir=face_cache_dir,
            device=device,
            output_transform=output_transform,
            hubert_device=hubert_device,
            model_backend=model_backend,
        )
        self.input_names = self.v2.model_backend.input_names
        self.frames, self.fps = self._load_template_frames(template_video, max_template_seconds)
        if not self.frames:
            raise RuntimeError(f"No template frames read from {template_video}")
        self.face_tracks, self.restore_contexts_by_face = self._build_multiface_contexts(
            min_faces=min_faces
        )
        self.frame_index = 0
        self.hn = np.zeros((2, 1, 576), dtype=np.float32)
        self.cn = np.zeros((2, 1, 576), dtype=np.float32)
        self.warmup()

    def _build_multiface_contexts(
        self, *, min_faces: int
    ) -> tuple[dict[str, FaceTrack], dict[str, list[FastRestoreContext]]]:
        first_detections = self._detect_frame_faces(self.frames[0])
        if len(first_detections) < min_faces:
            raise RuntimeError(f"expected at least {min_faces} faces")
        assigned_first = assign_face_ids_by_x(first_detections)
        face_ids = [face_id for face_id, _detection in assigned_first]
        face_tracks = {
            face_id: FaceTrack(face_id=face_id, order=order)
            for order, face_id in enumerate(face_ids)
        }
        contexts_by_face: dict[str, list[FastRestoreContext]] = {
            face_id: [] for face_id in face_ids
        }
        start = time.perf_counter()
        for frame_index, frame in enumerate(self.frames):
            detections = self._detect_frame_faces(frame)
            if len(detections) < len(face_ids):
                raise RuntimeError(
                    f"expected at least {len(face_ids)} faces in frame {frame_index}, got {len(detections)}"
                )
            assigned = assign_face_ids_by_x(detections)[: len(face_ids)]
            by_id = {face_id: detection for face_id, detection in assigned}
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            for face_id in face_ids:
                detection = by_id[face_id]
                crop = self.v2.image_processor.affine_transform_from_detection(rgb, detection)
                face_hwc = crop.face_chw.permute(1, 2, 0).cpu().numpy().astype(np.uint8)
                face_bgr = cv2.cvtColor(face_hwc, cv2.COLOR_RGB2BGR)
                contexts_by_face[face_id].append(
                    self._build_fast_restore_context(
                        frame=frame,
                        face=face_bgr,
                        coords=crop.box,
                        affine=crop.affine_matrix,
                    )
                )
        print(
            "v3_multiface_restore_context_seconds="
            f"{time.perf_counter() - start:.3f} faces={len(face_ids)} frames={len(self.frames)}",
            flush=True,
        )
        return face_tracks, contexts_by_face

    def _detect_frame_faces(self, frame: np.ndarray) -> list[FaceDetection]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return self.v2.image_processor.detect_faces(rgb)

    def make_multiface_state(self) -> MultiFaceSessionState:
        return MultiFaceSessionState(
            frame_index=0,
            face_states={
                face_id: RealtimeV3SessionState(
                    frame_index=0,
                    hn=np.zeros((2, 1, 576), dtype=np.float32),
                    cn=np.zeros((2, 1, 576), dtype=np.float32),
                )
                for face_id in self.restore_contexts_by_face
            },
        )

    def warmup(self) -> None:
        if not self.restore_contexts_by_face:
            return
        state = self.make_multiface_state()
        face_id = next(iter(self.restore_contexts_by_face))
        dummy_rep = np.zeros((10, 1024), dtype=np.float32)
        self._render_face_rep(face_id, dummy_rep, state, self._base_frame_for_index(0))

    def _template_index_for_frame(self, frame_index: int) -> int:
        n = len(self.frames)
        cycle = frame_index // n
        offset = frame_index % n
        return offset if cycle % 2 == 0 else n - 1 - offset

    def _base_frame_for_index(self, frame_index: int) -> np.ndarray:
        return self.frames[self._template_index_for_frame(frame_index)].copy()

    def _idle_anchor_mask(self, context: FastRestoreContext) -> np.ndarray:
        mask = context.soft_mask_roi_3d[0].detach().cpu().numpy().astype(np.float32)
        if getattr(self, "idle_anchor_mode", "none") == "face":
            return mask
        roi_h = mask.shape[0]
        start = min(max(int(roi_h * getattr(self, "idle_anchor_start", 0.55)), 0), roi_h)
        weights = np.zeros((roi_h,), dtype=np.float32)
        if start == 0:
            weights[:] = 1.0
            return mask * weights[:, None]
        if start < roi_h:
            ramp = max(int(roi_h * 0.12), 1)
            ramp_end = min(start + ramp, roi_h)
            weights[start:ramp_end] = np.linspace(0.0, 1.0, ramp_end - start, dtype=np.float32)
            weights[ramp_end:] = 1.0
        return mask * weights[:, None]

    def _apply_idle_anchor_face(self, base_frame: np.ndarray, face_id: str) -> np.ndarray:
        if getattr(self, "idle_anchor_mode", "none") == "none":
            return base_frame
        contexts = self.restore_contexts_by_face.get(face_id)
        if not contexts:
            return base_frame
        context = contexts[0]
        x0, y0, x1, y1 = context.roi
        output = base_frame.copy()
        anchor_roi = context.frame[y0:y1, x0:x1].astype(np.float32)
        base_roi = output[y0:y1, x0:x1].astype(np.float32)
        mask = self._idle_anchor_mask(context)[..., None]
        blended = anchor_roi * mask + base_roi * (1.0 - mask)
        output[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
        return output

    def _base_frame_with_idle_anchor(self, frame_index: int, face_id: str | None = None) -> np.ndarray:
        base_frame = self._base_frame_for_index(frame_index)
        if face_id is None or getattr(self, "idle_anchor_mode", "none") == "none":
            return base_frame
        return self._apply_idle_anchor_face(base_frame, face_id)

    def _tail_fade_mouth_weight(self, context: FastRestoreContext) -> torch.Tensor:
        template = context.soft_mask_roi_3d
        _channels, roi_h, _roi_w = template.shape
        start = min(max(int(round(roi_h * getattr(self, "tail_fade_mouth_start", 0.5))), 0), roi_h)
        ramp = max(int(round(roi_h * getattr(self, "tail_fade_mouth_ramp", 0.18))), 1)
        weights = torch.zeros((roi_h,), device=template.device, dtype=template.dtype)
        if start < roi_h:
            ramp_end = min(start + ramp, roi_h)
            weights[start:ramp_end] = torch.linspace(
                0.0,
                1.0,
                ramp_end - start,
                device=template.device,
                dtype=template.dtype,
            )
            weights[ramp_end:] = 1.0
        return weights.view(1, roi_h, 1).expand_as(template)

    def _smooth_box_weight(
        self,
        context: FastRestoreContext,
        *,
        top: float,
        bottom: float,
        left: float,
        right: float,
        ramp: float,
    ) -> torch.Tensor | None:
        template = context.soft_mask_roi_3d
        _channels, roi_h, roi_w = template.shape
        if top >= bottom or left >= right:
            return None
        device = template.device
        dtype = template.dtype
        y = torch.linspace(0.0, 1.0, roi_h, device=device, dtype=dtype)
        x = torch.linspace(0.0, 1.0, roi_w, device=device, dtype=dtype)
        ramp = max(float(ramp), 1e-6)
        y_weight = ((y - float(top)) / ramp).clamp(0.0, 1.0)
        y_weight = y_weight * ((float(bottom) - y) / ramp).clamp(0.0, 1.0)
        x_weight = ((x - float(left)) / ramp).clamp(0.0, 1.0)
        x_weight = x_weight * ((float(right) - x) / ramp).clamp(0.0, 1.0)
        weight = y_weight[:, None] * x_weight[None, :]
        return weight.unsqueeze(0).expand_as(template)

    def _mouth_hold_weight(self, context: FastRestoreContext) -> torch.Tensor | None:
        return self._smooth_box_weight(
            context,
            top=0.35,
            bottom=0.80,
            left=0.18,
            right=0.82,
            ramp=0.12,
        )

    def _combined_paste_weight(
        self,
        context: FastRestoreContext,
        blend_alpha: float,
    ) -> torch.Tensor | None:
        paste_strength = min(max(float(getattr(self, "paste_strength", 1.0)), 0.0), 1.0)
        weights: list[torch.Tensor] = []
        if getattr(self, "tail_fade_region", "mouth") == "mouth" and blend_alpha < 1.0:
            mouth_weight = self._tail_fade_mouth_weight(context)
            weights.append(mouth_weight + float(blend_alpha) * (1.0 - mouth_weight))
        if not weights:
            if paste_strength >= 1.0:
                return None
            return torch.full_like(context.soft_mask_roi_3d, paste_strength)
        output = weights[0]
        for weight in weights[1:]:
            output = output * weight
        return output * paste_strength

    def _mouth_hold_frame_count(self) -> int:
        return max(0, int(round(getattr(self, "mouth_hold_ms", 0) * self.fps / 1000.0)))

    def _capture_mouth_hold(
        self,
        face_id: str,
        frame: np.ndarray,
        frame_index: int,
    ) -> MouthHoldState | None:
        hold_frames = self._mouth_hold_frame_count()
        if hold_frames <= 0:
            return None
        context = self._context_for_face(face_id, frame_index)
        x0, y0, x1, y1 = context.roi
        weight_t = self._mouth_hold_weight(context)
        if weight_t is None:
            weight_t = context.soft_mask_roi_3d
        weight = weight_t[0].detach().cpu().numpy().astype(np.float32)
        return MouthHoldState(
            face_id=face_id,
            frame_index=frame_index,
            hold_frames=hold_frames,
            roi=context.roi,
            patch=frame[y0:y1, x0:x1].copy(),
            weight=weight,
        )

    def _apply_mouth_hold(
        self,
        base_frame: np.ndarray,
        hold: MouthHoldState | None,
        frame_index: int,
    ) -> np.ndarray:
        if hold is None:
            return base_frame
        age = frame_index - hold.frame_index - 1
        if age < 0 or age >= hold.hold_frames:
            return base_frame
        context = self._context_for_face(hold.face_id, frame_index)
        x0, y0, x1, y1 = context.roi
        target_h = y1 - y0
        target_w = x1 - x0
        patch = hold.patch
        weight = hold.weight
        if patch.shape[:2] != (target_h, target_w):
            patch = cv2.resize(patch, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        if weight.shape != (target_h, target_w):
            weight = cv2.resize(weight, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        alpha = (hold.hold_frames - age) / float(hold.hold_frames)
        alpha_weight = np.clip(weight * alpha, 0.0, 1.0)[..., None]
        output = base_frame.copy()
        base_roi = output[y0:y1, x0:x1].astype(np.float32)
        blended = patch.astype(np.float32) * alpha_weight + base_roi * (1.0 - alpha_weight)
        output[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
        return output

    def _context_for_face(self, face_id: str, frame_index: int) -> FastRestoreContext:
        contexts = self.restore_contexts_by_face.get(face_id)
        if contexts is None:
            raise ValueError(f"unknown face_id: {face_id}")
        return contexts[self._template_index_for_frame(frame_index)]

    def _render_face_rep(
        self,
        face_id: str,
        rep: np.ndarray,
        state: MultiFaceSessionState,
        base_frame: np.ndarray,
        blend_alpha: float = 1.0,
    ) -> np.ndarray:
        face_state = state.face_states.get(face_id)
        if face_state is None:
            raise ValueError(f"unknown face_id: {face_id}")
        context = self._context_for_face(face_id, state.frame_index)
        blend_alpha = min(max(float(blend_alpha), 0.0), 1.0)
        if blend_alpha <= 0.0:
            return base_frame
        if face_state.hn is None or face_state.cn is None:
            raise RuntimeError("QuickTalk face session state is not initialized")
        g, hn_out, cn_out = self.v2.run_model(
            rep[None, ...].astype(np.float32),
            context.face_input,
            face_state.hn,
            face_state.cn,
        )
        face_state.hn, face_state.cn = hn_out, cn_out
        g_arr = g.squeeze(0)
        if g_arr.dtype != np.float32:
            g_arr = g_arr.astype(np.float32)
        patch_t = torch.from_numpy(g_arr).to(
            device=self.v2.device, dtype=self.v2.dtype, non_blocking=True
        )
        patch_t = self.v2.transform_output_torch(patch_t)
        x1, y1, x2, y2 = context.coords
        patch_t = F.interpolate(
            patch_t.unsqueeze(0),
            size=(int(y2 - y1), int(x2 - x1)),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        ).squeeze(0)
        paste_weight = self._combined_paste_weight(context, blend_alpha)
        generated = self.fast_restore_img(
            context,
            patch_t,
            base_frame=base_frame,
            paste_weight=paste_weight,
        )
        if blend_alpha >= 1.0:
            return generated
        x0, y0, x1, y1 = context.roi
        output = generated.copy()
        blended_roi = (
            generated[y0:y1, x0:x1].astype(np.float32) * blend_alpha
            + base_frame[y0:y1, x0:x1].astype(np.float32) * (1.0 - blend_alpha)
        )
        output[y0:y1, x0:x1] = np.clip(blended_roi, 0, 255).astype(np.uint8)
        return output

    def _segment_reps(self, segment: MultiFaceSegment) -> Sequence[np.ndarray]:
        if segment.reps is not None:
            return segment.reps
        if segment.audio is None:
            raise ValueError(f"segment for speaker_id {segment.speaker_id} has no audio or reps")
        reps, _feature_seconds = self.prepare_wav_features(Path(segment.audio))
        return reps

    def _validate_segment_route(
        self,
        segments: Sequence[MultiFaceSegment],
        speaker_faces: Mapping[str, str],
    ) -> list[MultiFaceSegment]:
        previous_end = -1
        ordered = sorted(segments, key=lambda item: (item.start_ms, item.end_ms))
        for segment in ordered:
            if segment.speaker_id not in speaker_faces:
                raise ValueError(f"unknown speaker_id: {segment.speaker_id}")
            if speaker_faces[segment.speaker_id] not in self.restore_contexts_by_face:
                raise ValueError(f"unknown face_id: {speaker_faces[segment.speaker_id]}")
            if segment.end_ms <= segment.start_ms:
                raise ValueError(f"invalid segment duration for speaker_id: {segment.speaker_id}")
            if previous_end > segment.start_ms:
                raise ValueError("overlapping segments are not supported")
            previous_end = segment.end_ms
        return ordered

    def _segment_tail_blend_alpha(self, rep_index: int, rep_count: int) -> float:
        fade_frames = int(round(getattr(self, "tail_fade_ms", 0) * self.fps / 1000.0))
        if fade_frames <= 0 or rep_count <= 0:
            return 1.0
        remaining_after_current = rep_count - rep_index - 1
        if remaining_after_current >= fade_frames:
            return 1.0
        if fade_frames == 1:
            return 0.0
        return remaining_after_current / float(fade_frames - 1)

    def generate_frames_from_segments(
        self,
        segments: Sequence[MultiFaceSegment],
        speaker_faces: Mapping[str, str],
        state: MultiFaceSessionState | None = None,
    ) -> Iterator[np.ndarray]:
        state = state or self.make_multiface_state()
        mouth_hold: MouthHoldState | None = None
        for segment in self._validate_segment_route(segments, speaker_faces):
            start_frame = max(0, int(round(segment.start_ms * self.fps / 1000.0)))
            while state.frame_index < start_frame:
                base_frame = self._base_frame_for_index(state.frame_index)
                yield self._apply_mouth_hold(base_frame, mouth_hold, state.frame_index)
                state.frame_index += 1

            face_id = speaker_faces[segment.speaker_id]
            reps = list(self._segment_reps(segment))
            for rep_index, rep in enumerate(reps):
                blend_alpha = self._segment_tail_blend_alpha(rep_index, len(reps))
                base_frame = self._base_frame_for_index(state.frame_index)
                output = self._render_face_rep(face_id, rep, state, base_frame, blend_alpha=blend_alpha)
                if blend_alpha > 0.0:
                    mouth_hold = self._capture_mouth_hold(face_id, output, state.frame_index)
                yield output
                state.frame_index += 1

    def generate_frames_from_script(
        self,
        script: Mapping[str, Any],
        state: MultiFaceSessionState | None = None,
    ) -> Iterator[np.ndarray]:
        speaker_faces, segments = validate_multiface_script(script)
        return self.generate_frames_from_segments(segments, speaker_faces, state=state)

    def generate_video_from_script(
        self,
        script: Mapping[str, Any],
        audio_path: Path,
        output_path: Path,
        video_codec: str = "libx264",
        ffmpeg_preset: str = "veryfast",
        ffmpeg_tune: str | None = "zerolatency",
        crf: int = 18,
    ) -> RealtimeStats:
        maybe_mkdir(output_path.parent)
        h, w = self.frames[0].shape[:2]
        stats = RealtimeStats()
        ffmpeg = ensure_ffmpeg()
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{w}x{h}",
            "-r",
            f"{self.fps:g}",
            "-i",
            "pipe:0",
            "-i",
            str(audio_path),
        ]
        cmd += self._ffmpeg_video_encode_args(video_codec, ffmpeg_preset, ffmpeg_tune, crf)
        cmd += ["-c:a", "aac", "-shortest", str(output_path)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.stdin is None:
            proc.kill()
            raise RuntimeError("Failed to open ffmpeg stdin pipe")

        start = time.perf_counter()
        try:
            for frame in self.generate_frames_from_script(script):
                if stats.frames == 0:
                    stats.first_frame_seconds = time.perf_counter() - start
                proc.stdin.write(np.ascontiguousarray(frame).tobytes())
                stats.frames += 1
        except Exception:
            proc.kill()
            proc.wait()
            raise
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        stats.generate_seconds = time.perf_counter() - start
        mux_start = time.perf_counter()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr is not None else ""
        return_code = proc.wait()
        stats.mux_seconds = time.perf_counter() - mux_start
        if return_code != 0:
            raise RuntimeError(f"ffmpeg pipe failed with code {return_code}: {stderr.strip()}")
        return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V3 realtime-oriented V2 worker with a wav-file stream simulation.")
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--template-video", required=True)
    parser.add_argument("--audio", required=True)
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
    parser.add_argument("--model-backend", choices=["auto", "pth", "onnx"], default="auto")
    parser.add_argument("--sink", choices=["ffmpeg-pipe", "opencv"], default="ffmpeg-pipe")
    parser.add_argument("--video-codec", default="libx264")
    parser.add_argument("--ffmpeg-preset", default="veryfast")
    parser.add_argument("--ffmpeg-tune", default="zerolatency")
    parser.add_argument("--crf", type=int, default=18)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asset_root = Path(args.asset_root)
    if asset_root.name != "hdModule" and (asset_root / "checkpoints").exists():
        pass
    elif (asset_root / "hdModule" / "checkpoints").exists():
        asset_root = asset_root / "hdModule"
    face_cache_dir = None
    if not args.no_face_cache:
        face_cache_dir = Path(args.face_cache_dir) if args.face_cache_dir else (asset_root / ".face_cache_v3")
    worker = RealtimeV3Worker(
        asset_root=asset_root,
        template_video=Path(args.template_video),
        face_cache_dir=face_cache_dir,
        device=args.device,
        output_transform=args.output_transform,
        scale_h=args.scale_h,
        scale_w=args.scale_w,
        resolution=args.resolution,
        max_template_seconds=args.max_template_seconds,
        neck_fade_start=args.neck_fade_start,
        neck_fade_end=args.neck_fade_end,
        model_backend=args.model_backend,
    )
    stats = worker.generate_video_from_wav(
        Path(args.audio),
        Path(args.output),
        sink=args.sink,
        video_codec=args.video_codec,
        ffmpeg_preset=args.ffmpeg_preset,
        ffmpeg_tune=args.ffmpeg_tune or None,
        crf=args.crf,
    )
    print(f"output={args.output}")
    print(f"sink={args.sink}")
    print(f"frames={stats.frames}")
    print(f"audio_feature_seconds={stats.audio_feature_seconds:.3f}")
    print(f"first_frame_seconds={stats.first_frame_seconds:.3f}")
    print(f"generate_seconds={stats.generate_seconds:.3f}")
    print(f"generate_fps={stats.fps:.2f}")
    print(f"mux_seconds={stats.mux_seconds:.3f}")


if __name__ == "__main__":
    main()
