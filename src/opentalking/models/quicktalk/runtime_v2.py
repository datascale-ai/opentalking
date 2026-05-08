#!/usr/bin/env python3
"""
Minimal Linux-runnable reconstruction of QuickTalk digital human inference.

This script is intentionally conservative: it rebuilds the core recovered pipeline
from the shipped Windows module without trying to mirror every internal optimization.
The focus is functional parity for testing on Linux GPU servers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import cv2
import kornia
import numpy as np
import onnxruntime as ort
import torch
import torch.nn.functional as F
from insightface.app import FaceAnalysis
from kornia.filters import gaussian_blur2d
from kornia.geometry.transform import invert_affine_transform, warp_affine
from transformers import HubertModel, Wav2Vec2FeatureExtractor
import wave


INSIGHTFACE_DETECT_SIZE = 640


def run_cmd(cmd: Sequence[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout}")


def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH")
    return ffmpeg


def maybe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def numpy_hwc_to_chw(image: np.ndarray) -> np.ndarray:
    return np.transpose(image, (2, 0, 1))


def numpy_chw_to_hwc(image: np.ndarray) -> np.ndarray:
    return np.transpose(image, (1, 2, 0))


def to_device_dtype(tensor: torch.Tensor, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    return tensor.to(device=device, dtype=dtype)


def save_tensor_rgb(path: Path, chw: np.ndarray) -> None:
    hwc = np.transpose(chw, (1, 2, 0))
    hwc = np.clip(hwc * 255.0, 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), cv2.cvtColor(hwc, cv2.COLOR_RGB2BGR))


def save_tensor_mask(path: Path, hw: np.ndarray) -> None:
    img = np.clip(hw * 255.0, 0, 255).astype(np.uint8)
    img_color = cv2.applyColorMap(img, cv2.COLORMAP_JET)
    cv2.imwrite(str(path), img_color)


def format_stats(name: str, arr: np.ndarray) -> str:
    arr = np.asarray(arr)
    return (
        f"{name}: shape={tuple(arr.shape)} dtype={arr.dtype} "
        f"min={arr.min():.6f} max={arr.max():.6f} mean={arr.mean():.6f}"
    )


@dataclass
class FaceCropResult:
    face_chw: torch.Tensor
    box: List[int]
    affine_matrix: np.ndarray


class AlignRestore:
    def __init__(
        self,
        align_points: int = 3,
        resolution: int = 256,
        device: torch.device | str = "cpu",
        dtype: torch.dtype = torch.float16,
    ) -> None:
        if align_points != 3:
            raise NotImplementedError("Only 3-point alignment is reconstructed")
        self.upscale_factor = 1
        ratio = resolution / 256.0 * 2.8
        self.crop_ratio = (ratio, ratio)
        self.face_template = np.array([[17, 20], [58, 20], [37.5, 40]], dtype=np.float32) * ratio
        self.face_size = (int(75 * self.crop_ratio[0]), int(100 * self.crop_ratio[1]))
        self.device = torch.device(device)
        self.dtype = dtype
        self.p_bias: torch.Tensor | None = None
        self.fill_value = torch.tensor([127, 127, 127], device=self.device, dtype=self.dtype)
        self.mask = torch.ones((1, 1, self.face_size[1], self.face_size[0]), device=self.device, dtype=self.dtype)

    def align_warp_face(self, img: np.ndarray, landmarks3: np.ndarray, smooth: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        affine_matrix, self.p_bias = self.transformation_from_points(
            landmarks3,
            self.face_template,
            smooth=smooth,
            p_bias=self.p_bias,
        )

        img_t = torch.from_numpy(img).to(device=self.device, dtype=self.dtype)
        img_t = img_t.permute(2, 0, 1).unsqueeze(0)
        affine_t = torch.from_numpy(affine_matrix).to(device=self.device, dtype=self.dtype).unsqueeze(0)
        cropped_face = warp_affine(
            img_t,
            affine_t,
            (self.face_size[1], self.face_size[0]),
            mode="bilinear",
            padding_mode="fill",
            fill_value=self.fill_value,
        )
        cropped_face = cropped_face.squeeze(0).permute(1, 2, 0).contiguous().to(dtype=torch.uint8).cpu().numpy()
        return cropped_face, affine_matrix

    def transformation_from_points(
        self,
        points1: torch.Tensor | np.ndarray,
        points0: torch.Tensor | np.ndarray,
        smooth: bool = True,
        p_bias: torch.Tensor | None = None,
    ) -> Tuple[np.ndarray, torch.Tensor | None]:
        if isinstance(points0, np.ndarray):
            points2 = torch.tensor(points0, device=self.device, dtype=torch.float32)
        else:
            points2 = points0.clone().to(device=self.device, dtype=torch.float32)

        if isinstance(points1, np.ndarray):
            points1_tensor = torch.tensor(points1, device=self.device, dtype=torch.float32)
        else:
            points1_tensor = points1.clone().to(device=self.device, dtype=torch.float32)

        c1 = torch.mean(points1_tensor, dim=0)
        c2 = torch.mean(points2, dim=0)

        points1_centered = points1_tensor - c1
        points2_centered = points2 - c2

        s1 = torch.std(points1_centered)
        s2 = torch.std(points2_centered)

        points1_normalized = points1_centered / s1
        points2_normalized = points2_centered / s2

        covariance = torch.matmul(points1_normalized.T, points2_normalized)
        u, _, v = torch.svd(covariance)
        r = torch.matmul(v, u.T)

        det = torch.det(r)
        if det < 0:
            v[:, -1] = -v[:, -1]
            r = torch.matmul(v, u.T)

        sr = (s2 / s1) * r
        t = c2.reshape(2, 1) - (s2 / s1) * torch.matmul(r, c1.reshape(2, 1))
        m = torch.cat((sr, t), dim=1)

        if smooth:
            bias = points2_normalized[2] - points1_normalized[2]
            if p_bias is None:
                p_bias = bias
            else:
                bias = p_bias * 0.2 + bias * 0.8
            p_bias = bias
            m[:, 2] = m[:, 2] + bias

        return m.cpu().numpy().astype(np.float32), p_bias

    def restore_img(
        self,
        input_img: np.ndarray,
        face: torch.Tensor | np.ndarray,
        affine_matrix: np.ndarray | torch.Tensor,
        scale_h: float = 1.0,
        scale_w: float = 1.0,
    ) -> np.ndarray:
        h, w, _ = input_img.shape

        input_t = torch.from_numpy(input_img).to(device=self.device, dtype=self.dtype).permute(2, 0, 1)
        if isinstance(face, np.ndarray):
            face_t = torch.from_numpy(face)
        else:
            face_t = face
        if isinstance(affine_matrix, np.ndarray):
            affine_t = torch.from_numpy(affine_matrix).to(device=self.device, dtype=self.dtype).unsqueeze(0)
        else:
            affine_t = affine_matrix.to(device=self.device, dtype=self.dtype).unsqueeze(0)

        inv_affine = invert_affine_transform(affine_t)
        face_t = face_t.to(device=self.device, dtype=self.dtype).unsqueeze(0)
        inv_face = warp_affine(
            face_t,
            inv_affine,
            (h, w),
            mode="bilinear",
            padding_mode="fill",
            fill_value=self.fill_value,
        ).squeeze(0)
        inv_face = inv_face.clamp(0, 1) * 255.0

        inv_mask = warp_affine(
            self.mask,
            inv_affine,
            (h, w),
            padding_mode="zeros",
        )
        inv_mask_erosion = kornia.morphology.erosion(
            inv_mask,
            torch.ones(
                (int(2 * self.upscale_factor), int(2 * self.upscale_factor)),
                device=self.device,
                dtype=self.dtype,
            ),
        )
        inv_mask_erosion_t = inv_mask_erosion.squeeze(0).expand_as(inv_face)
        pasted_face = inv_mask_erosion_t * inv_face
        total_face_area = int(torch.sum(inv_mask_erosion.float()).item())
        w_edge = int(math.sqrt(total_face_area)) // 20
        erosion_radius = w_edge * 2
        kernel = np.ones((int(erosion_radius * scale_h), int(erosion_radius * scale_w)), np.uint8)
        inv_mask_erosion_np = inv_mask_erosion.squeeze().cpu().numpy().astype(np.float32)
        inv_mask_center = cv2.erode(inv_mask_erosion_np, kernel)
        inv_mask_center_t = torch.from_numpy(inv_mask_center).to(device=self.device, dtype=self.dtype)[None, None, ...]

        blur_size = w_edge * 2 + 1
        sigma = 0.3 * ((blur_size - 1) * 0.5 - 1) + 0.8
        inv_soft_mask = gaussian_blur2d(inv_mask_center_t, (blur_size, blur_size), (sigma, sigma)).squeeze(0)
        inv_soft_mask_3d = inv_soft_mask.expand_as(inv_face)
        img_back = inv_soft_mask_3d * pasted_face + (1.0 - inv_soft_mask_3d) * input_t
        return img_back.permute(1, 2, 0).contiguous().to(dtype=torch.uint8).cpu().numpy()


class FaceDetector:
    def __init__(self, model_root: Path, device: torch.device | str, det_size: int = INSIGHTFACE_DETECT_SIZE) -> None:
        self.device = torch.device(device)
        providers = ["CUDAExecutionProvider"] if self.device.type == "cuda" else ["CPUExecutionProvider"]
        self.app = FaceAnalysis(
            root=str(model_root),
            allowed_modules=["detection", "landmark_2d_106"],
            providers=providers,
        )
        ctx_id = self.device.index if self.device.type == "cuda" and self.device.index is not None else 0
        self.app.prepare(ctx_id=ctx_id if self.device.type == "cuda" else -1, det_size=(det_size, det_size))

    def __call__(self, image_rgb: np.ndarray) -> Tuple[np.ndarray | None, np.ndarray | None]:
        faces = self.app.get(image_rgb)
        if not faces:
            return None, None
        face = max(faces, key=lambda x: float((x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1])))
        return np.asarray(face.bbox, dtype=np.float32), np.asarray(face.landmark_2d_106, dtype=np.float32)


class ImageProcessor:
    def __init__(self, auxiliary_root: Path, repair_path: Path, resolution: int, device: torch.device, dtype: torch.dtype) -> None:
        self.auxiliary_root = auxiliary_root
        self.resolution = resolution
        self.device = device
        self.dtype = dtype
        self.restorer = AlignRestore(align_points=3, resolution=resolution, device=device, dtype=dtype)
        self.face_detector: FaceDetector | None = None
        self.mask_image = self.load_fixed_mask(np.load(str(repair_path)))

    def load_fixed_mask(self, mask_image: np.ndarray) -> torch.Tensor:
        mask_image = cv2.cvtColor(mask_image, cv2.COLOR_BGR2RGB)
        mask_image = cv2.resize(mask_image, (self.resolution, self.resolution), interpolation=cv2.INTER_LANCZOS4)
        mask_image = mask_image.astype(np.float32) / 255.0
        return torch.from_numpy(numpy_hwc_to_chw(mask_image))

    def affine_transform(self, image_rgb: np.ndarray) -> FaceCropResult:
        if self.face_detector is None:
            self.face_detector = FaceDetector(self.auxiliary_root, device=self.device)
        bbox, landmark_2d_106 = self.face_detector(image_rgb)
        if bbox is None or landmark_2d_106 is None:
            raise RuntimeError("Face not detected")
        pt_left_eye = np.mean(landmark_2d_106[[43, 48, 49, 51, 50]], axis=0)
        pt_right_eye = np.mean(landmark_2d_106[101:106], axis=0)
        pt_nose = np.mean(landmark_2d_106[[74, 77, 83, 86]], axis=0)
        landmarks3 = np.round([pt_left_eye, pt_right_eye, pt_nose]).astype(np.float32)
        face, affine_matrix = self.restorer.align_warp_face(image_rgb.copy(), landmarks3=landmarks3, smooth=True)
        box = [0, 0, face.shape[1], face.shape[0]]
        face = cv2.resize(face, (self.resolution, self.resolution), interpolation=cv2.INTER_LANCZOS4)
        face_chw = torch.from_numpy(numpy_hwc_to_chw(face))
        return FaceCropResult(face_chw=face_chw, box=box, affine_matrix=affine_matrix)

    def preprocess_fixed_mask_image(self, image: torch.Tensor, affine_transform: bool = False) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if affine_transform:
            image_np = image.permute(1, 2, 0).cpu().numpy().astype(np.uint8)
            crop = self.affine_transform(image_np)
            image = crop.face_chw
        else:
            image = image.float()
            if image.shape[-2:] != (self.resolution, self.resolution):
                image = F.interpolate(image.unsqueeze(0), size=(self.resolution, self.resolution), mode="bilinear", align_corners=False).squeeze(0)
        pixel_values = image / 255.0
        masked_pixel_values = pixel_values * self.mask_image
        return pixel_values, masked_pixel_values, self.mask_image[0:1]

    def prepare_masks_and_masked_images(self, images: np.ndarray | torch.Tensor, affine_transform: bool = False) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if isinstance(images, np.ndarray):
            images = torch.from_numpy(images)
        if images.shape[3] == 3:
            images = images.permute(0, 3, 1, 2)
        results = [self.preprocess_fixed_mask_image(image, affine_transform=affine_transform) for image in images]
        pixel_values_list, masked_pixel_values_list, masks_list = list(zip(*results))
        return torch.stack(pixel_values_list), torch.stack(masked_pixel_values_list), torch.stack(masks_list)


class QuickTalkRebuild:
    def __init__(
        self,
        asset_root: Path,
        batch_size: int = 8,
        sync_offset: int = 0,
        scale_h: float = 1.6,
        scale_w: float = 3.6,
        resolution: int = 256,
        video_padding_seconds: float = 0.0,
        face_cache_dir: Path | None = None,
        device: str = "cuda:0",
        output_transform: str = "bgr",
        debug_dir: Path | None = None,
        debug_frames: int = 0,
        hubert_device: str | None = None,
    ) -> None:
        self.asset_root = asset_root
        self.checkpoints = asset_root / "checkpoints"
        self.onnx_path = self.checkpoints / "256.onnx"
        self.repair_path = self.checkpoints / "repair.npy"
        self.hubert_path = self.checkpoints / "chinese-hubert-large"
        aux_min = self.checkpoints / "auxiliary_min"
        self.aux_root = aux_min if aux_min.exists() else (self.checkpoints / "auxiliary")
        self.batch_size = batch_size
        self.sync_offset = sync_offset
        self.scale_h = scale_h
        self.scale_w = scale_w
        self.resolution = resolution
        self.video_padding_seconds = max(0.0, float(video_padding_seconds))
        self.face_cache_dir = face_cache_dir
        self.device = torch.device(device)
        self.dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.output_transform = output_transform
        self.debug_dir = debug_dir
        self.debug_frames = debug_frames
        self._debug_saved = 0
        # The recovered model itself benefits from fp16 on CUDA, but the face
        # warp/restore path is numerically sensitive and should stay in fp32.
        self.image_processor = ImageProcessor(self.aux_root, self.repair_path, resolution, self.device, torch.float32)

        if self.device.type == "cuda":
            device_id = self.device.index if self.device.index is not None else 0
            providers = [
                ("CUDAExecutionProvider", {"device_id": device_id}),
                "CPUExecutionProvider",
            ]
        else:
            providers = ["CPUExecutionProvider"]
        self.ort_session = ort.InferenceSession(str(self.onnx_path), providers=providers)
        # HuBERT 可单独配到另一张卡，与 ONNX/restore_contexts 物理并行，
        # 消除每个流式块在块尾的 ~80ms HuBERT 串行 gap。默认与主 device 相同。
        self.hubert_device = (
            torch.device(hubert_device) if hubert_device else self.device
        )
        self.feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(str(self.hubert_path))
        self.hubert_model = HubertModel.from_pretrained(str(self.hubert_path)).to(self.hubert_device)
        if self.hubert_device.type == "cuda":
            self.hubert_model = self.hubert_model.half()
        self.hubert_model.eval()
        if self.debug_dir is not None:
            maybe_mkdir(self.debug_dir)
        if self.face_cache_dir is not None:
            maybe_mkdir(self.face_cache_dir)

    def transform_output(self, p: np.ndarray) -> np.ndarray:
        if self.output_transform == "rgb":
            return p
        if self.output_transform == "bgr":
            return p[[2, 1, 0], :, :]
        if self.output_transform == "tanh_rgb":
            return np.clip(p / 2.0 + 0.5, 0.0, 1.0)
        if self.output_transform == "tanh_bgr":
            return np.clip(p[[2, 1, 0], :, :] / 2.0 + 0.5, 0.0, 1.0)
        raise ValueError(f"Unsupported output transform: {self.output_transform}")

    def transform_output_torch(self, p_t: torch.Tensor) -> torch.Tensor:
        """GPU 版 transform_output：避免每帧 numpy↔cuda 来回搬。

        传入 ``p_t`` 形状为 ``(C, H, W)``，已在目标 device 上。返回同样形状。
        """
        if self.output_transform == "rgb":
            return p_t
        if self.output_transform == "bgr":
            return p_t[[2, 1, 0], :, :]
        if self.output_transform == "tanh_rgb":
            return (p_t / 2.0 + 0.5).clamp(0.0, 1.0)
        if self.output_transform == "tanh_bgr":
            return (p_t[[2, 1, 0], :, :] / 2.0 + 0.5).clamp(0.0, 1.0)
        raise ValueError(f"Unsupported output transform: {self.output_transform}")

    def maybe_dump_debug(
        self,
        face_input: np.ndarray,
        rep_input: np.ndarray,
        raw_pred: np.ndarray,
        frame: np.ndarray,
        affine_matrix: np.ndarray,
    ) -> None:
        if self.debug_dir is None or self._debug_saved >= self.debug_frames:
            return

        idx = self._debug_saved
        debug_frame_dir = self.debug_dir / f"frame_{idx:03d}"
        maybe_mkdir(debug_frame_dir)

        mask = face_input[0:1]
        masked_face = face_input[1:4]
        ref_face = face_input[4:7]
        transform_variants = {
            "raw_rgb": np.clip(raw_pred, 0.0, 1.0),
            "raw_bgrswap": np.clip(raw_pred[[2, 1, 0], :, :], 0.0, 1.0),
            "tanh_rgb": np.clip(raw_pred / 2.0 + 0.5, 0.0, 1.0),
            "tanh_bgrswap": np.clip(raw_pred[[2, 1, 0], :, :] / 2.0 + 0.5, 0.0, 1.0),
        }

        save_tensor_mask(debug_frame_dir / "mask.png", mask[0])
        save_tensor_rgb(debug_frame_dir / "masked_face.png", masked_face)
        save_tensor_rgb(debug_frame_dir / "ref_face.png", ref_face)
        for name, variant in transform_variants.items():
            save_tensor_rgb(debug_frame_dir / f"{name}.png", variant)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        cv2.imwrite(str(debug_frame_dir / "frame.png"), cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))

        stats_lines = [
            format_stats("audio", rep_input),
            format_stats("mask", mask),
            format_stats("masked_face", masked_face),
            format_stats("ref_face", ref_face),
            format_stats("raw_pred", raw_pred),
        ]
        for name, variant in transform_variants.items():
            stats_lines.append(format_stats(name, variant))
        stats_lines.append(f"affine_matrix:\n{affine_matrix}")
        (debug_frame_dir / "stats.txt").write_text("\n".join(stats_lines) + "\n", encoding="utf-8")
        self._debug_saved += 1

    def preprocess_media(self, video_path: Path, audio_path: Path, workdir: Path) -> Tuple[Path, Path]:
        ffmpeg = ensure_ffmpeg()
        video_25 = workdir / "fps25_temp.mp4"
        audio_16k = workdir / "audio_temp.wav"
        run_cmd([ffmpeg, "-y", "-i", str(audio_path), "-ac", "1", "-ar", "16000", str(audio_16k)])
        audio_duration = self.audio_duration(audio_16k)
        video_cut_duration = audio_duration + self.video_padding_seconds

        cap = cv2.VideoCapture(str(video_path))
        src_fps = float(cap.get(cv2.CAP_PROP_FPS))
        cap.release()
        if src_fps <= 0:
            raise RuntimeError(f"Invalid FPS from video: {video_path}")

        if abs(src_fps - 25.0) > 1e-3:
            run_cmd(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(video_path),
                    "-r",
                    "25",
                    "-t",
                    str(video_cut_duration),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_25),
                ]
            )
        else:
            video_25 = video_path
        return video_25, audio_16k

    def read_frames(self, video_path: Path, max_seconds: float | None = None) -> Tuple[List[np.ndarray], float]:
        cap = cv2.VideoCapture(str(video_path))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if fps <= 0:
            raise RuntimeError(f"Invalid FPS from video: {video_path}")
        frames: List[np.ndarray] = []
        frame_limit = None if max_seconds is None else int(max_seconds * fps)
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
            idx += 1
            if frame_limit is not None and idx >= frame_limit:
                break
        cap.release()
        return frames, fps

    def audio_duration(self, wav_path: Path) -> float:
        with wave.open(str(wav_path), "rb") as wav:
            return float(wav.getnframes()) / float(wav.getframerate())

    @torch.inference_mode()
    def extract_representations(self, wav_path: Path) -> np.ndarray:
        with wave.open(str(wav_path), "rb") as wav_file:
            sr = wav_file.getframerate()
            sampwidth = wav_file.getsampwidth()
            n_channels = wav_file.getnchannels()
            raw = wav_file.readframes(wav_file.getnframes())
        if sampwidth == 2:
            wav = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 4:
            wav = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise RuntimeError(f"Unsupported WAV sample width: {sampwidth}")
        if n_channels > 1:
            wav = wav.reshape(-1, n_channels).mean(axis=1)
        return self._run_hubert(wav, sr)

    @torch.inference_mode()
    def extract_representations_pcm(self, pcm: np.ndarray, sample_rate: int) -> np.ndarray:
        arr = np.asarray(pcm).reshape(-1)
        if arr.dtype == np.int16:
            wav = arr.astype(np.float32) / 32768.0
        elif arr.dtype == np.int32:
            wav = arr.astype(np.float32) / 2147483648.0
        elif arr.dtype in (np.float32, np.float64):
            wav = arr.astype(np.float32, copy=False)
        else:
            raise RuntimeError(f"Unsupported PCM dtype: {arr.dtype}")
        return self._run_hubert(wav, int(sample_rate))

    # HuBERT-large feature_extractor convolutional stack needs at least
    # ~400 samples (25ms@16kHz). Shorter inputs blow up with
    # ``RuntimeError: Calculated padded input size per channel: (1)``.
    _MIN_HUBERT_SAMPLES_16K = 480  # 30ms — safe margin above the kernel stack's minimum.

    def _run_hubert(self, wav: np.ndarray, sr: int) -> np.ndarray:
        wav = np.asarray(wav, dtype=np.float32).reshape(-1)
        min_samples = max(1, int(round(self._MIN_HUBERT_SAMPLES_16K * sr / 16000.0)))
        if wav.size < min_samples:
            wav = np.pad(wav, (0, min_samples - wav.size), mode="constant")
        inputs = self.feature_extractor(wav, sampling_rate=sr, return_tensors="pt").input_values.to(self.hubert_device)
        if self.hubert_device.type == "cuda":
            inputs = inputs.half()
        outputs = self.hubert_model(inputs)
        return outputs.last_hidden_state.permute(0, 2, 1).detach().cpu().numpy()

    def build_rep_chunks(self, repst: np.ndarray, n_frames: int, fps: float) -> List[np.ndarray]:
        rep_chunks: List[np.ndarray] = []
        rep_step_size = 10
        rep_idx_multiplier = 50.0 / fps
        seq_len = repst.shape[-1]
        # ONNX 模型要求每个 rep chunk 形状固定为 (rep_step_size, hidden)。
        # 当总 seq_len < rep_step_size（PCM 太短，HuBERT 输出帧数不足）时，
        # 在尾部 zero-pad 到 rep_step_size，保证后续 ``self._right_pad`` 切片
        # 永远拿到正好 ``rep_step_size`` 帧，避免 ONNX
        # ``Got invalid dimensions for input: audio`` 报错。
        if seq_len < rep_step_size:
            pad_width = rep_step_size - seq_len
            repst = np.pad(repst, ((0, 0), (0, 0), (0, pad_width)), mode="constant")
            seq_len = repst.shape[-1]
        for i in range(n_frames):
            start_idx = int(max(i + self.sync_offset, 0) * rep_idx_multiplier)
            if start_idx + rep_step_size > seq_len:
                chunk = repst[0, :, seq_len - rep_step_size : seq_len]
            else:
                chunk = repst[0, :, start_idx : start_idx + rep_step_size]
            rep_chunks.append(chunk.T.astype(np.float32))
        return rep_chunks

    def face_detect_frames(self, frames: Sequence[np.ndarray]) -> List[Tuple[np.ndarray, List[int], np.ndarray]]:
        results = []
        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            crop = self.image_processor.affine_transform(rgb)
            face_hwc = crop.face_chw.permute(1, 2, 0).cpu().numpy().astype(np.uint8)
            face_bgr = cv2.cvtColor(face_hwc, cv2.COLOR_RGB2BGR)
            results.append((face_bgr, crop.box, crop.affine_matrix))
        return results

    def face_cache_path(self, source_video: Path, n_frames: int, fps: float, read_limit: float) -> Path | None:
        if self.face_cache_dir is None:
            return None
        try:
            stat = source_video.stat()
            payload = {
                "path": str(source_video.resolve()),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "n_frames": n_frames,
                "fps": round(float(fps), 6),
                "read_limit": round(float(read_limit), 6),
                "resolution": self.resolution,
                "aux_root": str(self.aux_root.resolve()),
            }
        except OSError:
            return None
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        return self.face_cache_dir / f"face_{key}.npz"

    def load_face_cache(self, cache_path: Path) -> List[Tuple[np.ndarray, List[int], np.ndarray]] | None:
        if not cache_path.exists():
            return None
        try:
            data = np.load(str(cache_path), allow_pickle=False)
            faces = data["faces"]
            affines = data["affines"]
            boxes = data["boxes"] if "boxes" in data.files else None
            if faces.ndim != 4 or affines.ndim != 3 or len(faces) != len(affines):
                return None
            if boxes is None or boxes.ndim != 2 or boxes.shape[1] != 4 or len(boxes) != len(faces):
                return None
            return [(faces[i], boxes[i].astype(np.int32).tolist(), affines[i]) for i in range(len(faces))]
        except Exception:
            return None

    def save_face_cache(self, cache_path: Path, results: Sequence[Tuple[np.ndarray, List[int], np.ndarray]]) -> None:
        try:
            maybe_mkdir(cache_path.parent)
            faces = np.stack([item[0] for item in results], axis=0).astype(np.uint8)
            boxes = np.asarray([item[1] for item in results], dtype=np.int32)
            affines = np.stack([item[2] for item in results], axis=0).astype(np.float32)
            tmp_path = cache_path.with_suffix(".tmp.npz")
            np.savez(str(tmp_path), faces=faces, boxes=boxes, affines=affines)
            tmp_path.replace(cache_path)
        except Exception:
            pass

    def datagen(
        self,
        frames: Sequence[np.ndarray],
        reps: Sequence[np.ndarray],
        face_det_results: Sequence[Tuple[np.ndarray, List[int], np.ndarray]] | None = None,
    ) -> Iterable[Tuple[np.ndarray, np.ndarray, List[np.ndarray], List[List[int]], List[np.ndarray]]]:
        img_batch: List[np.ndarray] = []
        rep_batch: List[np.ndarray] = []
        frame_batch: List[np.ndarray] = []
        coords_batch: List[List[int]] = []
        affines_batch: List[np.ndarray] = []

        if len(reps) == 0 or len(frames) == 0:
            raise RuntimeError("invalid video/audio length")

        effective_len = min(len(frames), len(reps))
        if effective_len <= 0:
            raise RuntimeError("invalid video/audio length")
        if effective_len < len(frames):
            frames = frames[:effective_len]

        if face_det_results is None:
            face_det_results = self.face_detect_frames(frames)
        n_frames = len(frames)
        for i, rep in enumerate(reps):
            if i // n_frames % 2 == 0:
                idx = i % n_frames
            else:
                idx = n_frames - 1 - (i % n_frames)

            frame_to_save = frames[idx].copy()
            face, coords, affine_matrix = face_det_results[idx]
            face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
            img_batch.append(face)
            rep_batch.append(rep)
            frame_batch.append(frame_to_save)
            coords_batch.append(coords)
            affines_batch.append(affine_matrix)

            if len(img_batch) >= self.batch_size:
                yield self._prepare_batch(img_batch, rep_batch, frame_batch, coords_batch, affines_batch)
                img_batch, rep_batch, frame_batch, coords_batch, affines_batch = [], [], [], [], []

        if img_batch:
            yield self._prepare_batch(img_batch, rep_batch, frame_batch, coords_batch, affines_batch)

    def _prepare_batch(
        self,
        img_batch: List[np.ndarray],
        rep_batch: List[np.ndarray],
        frame_batch: List[np.ndarray],
        coords_batch: List[List[int]],
        affines_batch: List[np.ndarray],
    ) -> Tuple[np.ndarray, np.ndarray, List[np.ndarray], List[List[int]], List[np.ndarray]]:
        img_arr = np.asarray(img_batch)
        rep_arr = np.asarray(rep_batch)
        ref_pixel_values, masked_pixel_values, masks = self.image_processor.prepare_masks_and_masked_images(img_arr, affine_transform=False)
        face_input = torch.cat((masks, masked_pixel_values, ref_pixel_values), dim=1).numpy().astype(np.float32)
        rep_input = rep_arr.astype(np.float32)
        return face_input, rep_input, frame_batch, coords_batch, affines_batch

    def infer_video(self, video_path: Path, audio_path: Path, output_path: Path, limit_seconds: float | None = None) -> Path:
        maybe_mkdir(output_path.parent)
        with tempfile.TemporaryDirectory(prefix="quicktalk_rebuild_") as tmpdir:
            workdir = Path(tmpdir)
            video_25, audio_16k = self.preprocess_media(video_path, audio_path, workdir)
            audio_duration = self.audio_duration(audio_16k)
            read_limit = audio_duration + self.video_padding_seconds
            if limit_seconds is not None:
                read_limit = min(read_limit, limit_seconds)

            frames, fps = self.read_frames(video_25, max_seconds=read_limit)
            if not frames:
                raise RuntimeError("No frames read from video")

            repst = self.extract_representations(audio_16k)
            rep_chunks = self.build_rep_chunks(repst, len(frames), fps)

            h, w = frames[0].shape[:2]
            temp_video = workdir / "video_temp.avi"
            writer = cv2.VideoWriter(
                str(temp_video),
                cv2.VideoWriter_fourcc(*"DIVX"),
                fps,
                (w, h),
            )
            if not writer.isOpened():
                raise RuntimeError(f"Failed to open VideoWriter for {temp_video}")

            hn = np.zeros((2, 1, 576), dtype=np.float32)
            cn = np.zeros((2, 1, 576), dtype=np.float32)
            input_names = [x.name for x in self.ort_session.get_inputs()]

            total_frames = 0
            cache_path = self.face_cache_path(video_path, len(frames), fps, read_limit)
            face_det_results = self.load_face_cache(cache_path) if cache_path is not None else None
            if face_det_results is None or len(face_det_results) != len(frames):
                face_t0 = time.perf_counter()
                face_det_results = self.face_detect_frames(frames)
                if cache_path is not None:
                    self.save_face_cache(cache_path, face_det_results)
                print(f"face_cache=miss face_detect_seconds={time.perf_counter() - face_t0:.3f} frames={len(frames)}", flush=True)
            else:
                print(f"face_cache=hit frames={len(face_det_results)} path={cache_path}", flush=True)

            for face_batch, rep_batch, frame_batch, coords_batch, affines_batch in self.datagen(frames, rep_chunks, face_det_results):
                pred_frames = []
                for frame_idx in range(face_batch.shape[0]):
                    x_face = face_batch[frame_idx : frame_idx + 1].astype(np.float32)
                    x_audio = rep_batch[frame_idx : frame_idx + 1].astype(np.float32)
                    g, hn, cn = self.ort_session.run(
                        None,
                        {
                            input_names[0]: x_audio,
                            input_names[1]: x_face,
                            input_names[2]: hn,
                            input_names[3]: cn,
                        },
                    )
                    self.maybe_dump_debug(
                        x_face[0],
                        x_audio[0],
                        g.squeeze(0).astype(np.float32),
                        frame_batch[frame_idx],
                        affines_batch[frame_idx],
                    )
                    pred_frames.append(g.squeeze(0).astype(np.float32))

                pred = np.stack(pred_frames, axis=0)
                for p, f, c, a in zip(pred, frame_batch, coords_batch, affines_batch):
                    x1, y1, x2, y2 = c
                    height = int(y2 - y1)
                    width = int(x2 - x1)
                    p = self.transform_output(p)
                    p_t = torch.from_numpy(p).to(device=self.device, dtype=self.dtype)
                    p_t = F.interpolate(
                        p_t.unsqueeze(0),
                        size=(height, width),
                        mode="bicubic",
                        align_corners=False,
                        antialias=True,
                    ).squeeze(0)
                    merged = self.image_processor.restorer.restore_img(f, p_t, a, scale_h=self.scale_h, scale_w=self.scale_w)
                    writer.write(merged)
                    total_frames += 1
            writer.release()

            ffmpeg = ensure_ffmpeg()
            run_cmd(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(temp_video),
                    "-i",
                    str(audio_16k),
                    "-c:v",
                    "libx264",
                    "-crf",
                    "16",
                    "-preset",
                    "superfast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-shortest",
                    str(output_path),
                ]
            )
            if total_frames == 0:
                raise RuntimeError("No frames were generated")
        return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild and run QuickTalk digital human inference on Linux.")
    parser.add_argument("--asset-root", required=True, help="Path to hdModule root or equivalent asset directory")
    parser.add_argument("--video", required=True, help="Source portrait video")
    parser.add_argument("--audio", required=True, help="Driving audio")
    parser.add_argument("--output", required=True, help="Output mp4 path")
    parser.add_argument("--device", default="cuda:0", help="Torch device, e.g. cuda:0 or cpu")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--sync-offset", type=int, default=0)
    parser.add_argument("--scale-h", type=float, default=1.6)
    parser.add_argument("--scale-w", type=float, default=3.6)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument(
        "--video-padding-seconds",
        type=float,
        default=0.0,
        help="Extra source-video seconds to process beyond the audio duration. Default avoids generating frames that ffmpeg later drops.",
    )
    parser.add_argument("--face-cache-dir", default=None, help="Directory for cached V2 face crops/affines. Defaults to <asset-root>/.face_cache_v2")
    parser.add_argument("--no-face-cache", action="store_true", help="Disable V2 face crop cache")
    parser.add_argument("--limit-seconds", type=float, default=None, help="Optional upper bound for quick tests")
    parser.add_argument(
        "--output-transform",
        choices=["rgb", "bgr", "tanh_rgb", "tanh_bgr"],
        default="bgr",
        help="How to interpret ONNX output before paste-back",
    )
    parser.add_argument("--debug-dir", default=None, help="Optional directory for intermediate debug dumps")
    parser.add_argument("--debug-frames", type=int, default=0, help="How many frames to dump for debugging")
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
        face_cache_dir = Path(args.face_cache_dir) if args.face_cache_dir else (asset_root / ".face_cache_v2")

    rebuild = QuickTalkRebuild(
        asset_root=asset_root,
        batch_size=args.batch_size,
        sync_offset=args.sync_offset,
        scale_h=args.scale_h,
        scale_w=args.scale_w,
        resolution=args.resolution,
        video_padding_seconds=args.video_padding_seconds,
        face_cache_dir=face_cache_dir,
        device=args.device,
        output_transform=args.output_transform,
        debug_dir=Path(args.debug_dir) if args.debug_dir else None,
        debug_frames=args.debug_frames,
    )
    output = rebuild.infer_video(Path(args.video), Path(args.audio), Path(args.output), limit_seconds=args.limit_seconds)
    print(output)


if __name__ == "__main__":
    main()
