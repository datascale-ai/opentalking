from __future__ import annotations

import json
import math
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Literal, Mapping, cast

import numpy as np
import cv2
from PIL import Image, UnidentifiedImageError


CANONICAL_DOGO_AVATAR_ID = "dogo-light2d"
LIGHT2D_MODEL_TYPE = "mock"
DEFAULT_LIGHT2D_SAMPLE_RATE = 16_000
DEFAULT_LIGHT2D_FPS = 25

MouthState = Literal["closed", "small", "medium", "large"]


class Light2DContractError(ValueError):
    """Raised when a Light2D manifest, config, or referenced asset is invalid."""


@dataclass(frozen=True)
class Light2DRendererContext:
    avatar_dir: Path
    renderer_root: Path
    avatar_id: str
    model_type: str
    config: dict[str, Any]
    recommended_for: tuple[str, ...]
    referenced_assets: frozenset[str]


@dataclass(frozen=True)
class Light2DTransforms:
    breath_scale: float
    sway_degrees: float
    speaking_weight: float
    scale_y: float
    rotation_degrees: float


@dataclass(frozen=True)
class Light2DFrameState:
    timestamp_ms: float
    raw_energy: float
    energy: float
    mouth_state: MouthState
    previous_mouth_state: MouthState
    mouth_progress: float
    blinking: bool
    transforms: Light2DTransforms

    @classmethod
    def for_test(
        cls,
        *,
        mouth_state: MouthState = "closed",
        previous_mouth_state: MouthState = "closed",
        mouth_progress: float = 1.0,
        blinking: bool = False,
    ) -> Light2DFrameState:
        return cls(
            timestamp_ms=0.0,
            raw_energy=0.0,
            energy=0.0,
            mouth_state=mouth_state,
            previous_mouth_state=previous_mouth_state,
            mouth_progress=mouth_progress,
            blinking=blinking,
            transforms=Light2DTransforms(
                breath_scale=0.0,
                sway_degrees=0.0,
                speaking_weight=0.0,
                scale_y=1.0,
                rotation_degrees=0.0,
            ),
        )


@dataclass(frozen=True)
class Light2DRenderedFrame:
    rgba: np.ndarray
    state: Light2DFrameState


@dataclass(frozen=True)
class _PreloadedLayer:
    rgba: np.ndarray
    rect: tuple[int, int, int, int]


def safe_relative_path(value: object, *, suffix: str) -> Path | None:
    raw = str(value or "")
    if (
        not raw
        or raw.startswith("/")
        or "\\" in raw
        or "?" in raw
        or "#" in raw
        or ":" in raw
    ):
        return None
    parts = raw.split("/")
    if any(part in {"", ".", ".."} or "\x00" in part for part in parts):
        return None
    path = Path(*parts)
    return path if path.suffix.lower() == suffix else None


def _valid_rect(value: object, width: int, height: int) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        return False
    x, y, rect_width, rect_height = (float(item) for item in value)
    return (
        all(math.isfinite(item) for item in (x, y, rect_width, rect_height))
        and x >= 0
        and y >= 0
        and rect_width > 0
        and rect_height > 0
        and x + rect_width <= width
        and y + rect_height <= height
    )


def validate_light2d_config(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise Light2DContractError("invalid Light2D config version")
    canvas = raw.get("canvas")
    if not isinstance(canvas, dict):
        raise Light2DContractError("invalid Light2D canvas")
    width = canvas.get("width")
    height = canvas.get("height")
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or not 1 <= width <= 4096
        or not 1 <= height <= 4096
    ):
        raise Light2DContractError("invalid Light2D canvas size")

    layers = raw.get("layers")
    if not isinstance(layers, dict) or not isinstance(layers.get("mouth"), dict):
        raise Light2DContractError("invalid Light2D layers")
    entries = [layers.get("base"), layers.get("blink")]
    mouth = layers["mouth"]
    if set(mouth) != {"closed", "small", "medium", "large"}:
        raise Light2DContractError("invalid Light2D mouth layers")
    entries.extend(mouth[name] for name in ("closed", "small", "medium", "large"))
    for entry in entries:
        if not isinstance(entry, dict):
            raise Light2DContractError("invalid Light2D layer")
        if safe_relative_path(entry.get("source"), suffix=".png") is None:
            raise Light2DContractError("invalid Light2D layer source")
        if not _valid_rect(entry.get("rect"), width, height):
            raise Light2DContractError("invalid Light2D layer rectangle")

    audio = raw.get("audio")
    animation = raw.get("animation")
    if not isinstance(audio, dict) or not isinstance(animation, dict):
        raise Light2DContractError("invalid Light2D renderer parameters")
    numbers = {
        key: audio.get(key)
        for key in (
            "silence_gate",
            "small_threshold",
            "medium_threshold",
            "attack_ms",
            "release_ms",
            "crossfade_ms",
        )
    }
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in numbers.values()
    ):
        raise Light2DContractError("invalid Light2D audio parameters")
    silence_gate = cast(float, numbers["silence_gate"])
    small_threshold = cast(float, numbers["small_threshold"])
    medium_threshold = cast(float, numbers["medium_threshold"])
    attack_ms = cast(float, numbers["attack_ms"])
    release_ms = cast(float, numbers["release_ms"])
    crossfade_ms = cast(float, numbers["crossfade_ms"])
    if not 0 <= silence_gate < small_threshold < medium_threshold <= 1:
        raise Light2DContractError("invalid Light2D audio thresholds")
    if not all(1 <= value <= 2000 for value in (attack_ms, release_ms, crossfade_ms)):
        raise Light2DContractError("invalid Light2D audio timing")

    animation_numbers = {
        key: animation.get(key)
        for key in (
            "breath_period_ms",
            "breath_scale",
            "sway_degrees",
            "blink_period_ms",
            "blink_duration_ms",
        )
    }
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in animation_numbers.values()
    ):
        raise Light2DContractError("invalid Light2D animation parameters")
    breath_period_ms = cast(float, animation_numbers["breath_period_ms"])
    breath_scale = cast(float, animation_numbers["breath_scale"])
    sway_degrees = cast(float, animation_numbers["sway_degrees"])
    blink_period_ms = cast(float, animation_numbers["blink_period_ms"])
    blink_duration_ms = cast(float, animation_numbers["blink_duration_ms"])
    if (
        breath_period_ms <= 0
        or blink_period_ms <= 0
        or blink_duration_ms <= 0
        or not 0 <= breath_scale <= 0.05
        or abs(sway_degrees) > 5
    ):
        raise Light2DContractError("invalid Light2D animation range")
    return raw


@contextmanager
def _open_file_no_follow(root: Path, relative: Path) -> Iterator[BinaryIO]:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not no_follow or not directory:
        raise Light2DContractError("secure Light2D file opening is unavailable")
    root = root.absolute()
    if not root.is_absolute() or relative.is_absolute():
        raise Light2DContractError("invalid Light2D file path")
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(root.anchor, os.O_RDONLY | directory)
        for part in root.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | directory | no_follow, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        for part in relative.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | directory | no_follow, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(relative.name, os.O_RDONLY | no_follow, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise Light2DContractError("Light2D asset is not a regular file")
        with os.fdopen(file_fd, "rb") as opened:
            file_fd = None
            yield opened
    except (OSError, ValueError) as exc:
        raise Light2DContractError("Light2D asset not found") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _read_json_no_follow(root: Path, relative: Path, *, label: str) -> object:
    try:
        with _open_file_no_follow(root, relative) as opened:
            return json.loads(opened.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, Light2DContractError) as exc:
        raise Light2DContractError(f"invalid Light2D {label}") from exc


def _resolve_contained_file(root: Path, relative: Path) -> Path:
    with _open_file_no_follow(root, relative):
        pass
    return root / relative


def _referenced_asset_names(config: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        {
            config["layers"]["base"]["source"],
            config["layers"]["blink"]["source"],
            *(layer["source"] for layer in config["layers"]["mouth"].values()),
        }
    )


def load_light2d_renderer(
    avatar_dir: Path,
) -> Light2DRendererContext:
    try:
        avatar_root = avatar_dir.resolve(strict=True)
    except OSError as exc:
        raise Light2DContractError("invalid Light2D manifest") from exc
    manifest = _read_json_no_follow(avatar_root, Path("manifest.json"), label="manifest")
    if not isinstance(manifest, dict):
        raise Light2DContractError("invalid Light2D manifest")
    avatar_id = str(manifest.get("id") or "")
    model_type = str(manifest.get("model_type") or "")
    metadata = manifest.get("metadata")
    renderer = metadata.get("client_renderer") if isinstance(metadata, dict) else None
    if not isinstance(renderer, dict) or renderer.get("type") != "light2d":
        raise Light2DContractError("Light2D renderer not found")
    config_relative = safe_relative_path(renderer.get("config"), suffix=".json")
    if config_relative is None:
        raise Light2DContractError("invalid Light2D config path")
    raw_config = _read_json_no_follow(avatar_root, config_relative, label="config")
    config = validate_light2d_config(raw_config)
    recommended = renderer.get("recommended_for")
    recommended_for = tuple(
        str(item) for item in recommended if isinstance(item, str) and item
    ) if isinstance(recommended, list) else ()
    referenced_assets = _referenced_asset_names(config)
    context = Light2DRendererContext(
        avatar_dir=avatar_root,
        renderer_root=avatar_root / config_relative.parent,
        avatar_id=avatar_id,
        model_type=model_type,
        config=config,
        recommended_for=recommended_for,
        referenced_assets=referenced_assets,
    )
    for asset_path in referenced_assets:
        resolve_referenced_asset(context, asset_path)
    return context


def require_canonical_dogo(context: Light2DRendererContext) -> Light2DRendererContext:
    if (
        context.avatar_id != CANONICAL_DOGO_AVATAR_ID
        or context.avatar_dir.name != CANONICAL_DOGO_AVATAR_ID
        or context.model_type != LIGHT2D_MODEL_TYPE
    ):
        raise Light2DContractError("Light2D renderer is not canonical DOGO")
    return context


def load_canonical_dogo_renderer(avatar_dir: Path) -> Light2DRendererContext:
    return require_canonical_dogo(load_light2d_renderer(avatar_dir))


def resolve_referenced_asset(
    context: Light2DRendererContext,
    asset_path: object,
) -> Path:
    relative = safe_relative_path(asset_path, suffix=".png")
    if relative is None:
        raise Light2DContractError("invalid Light2D asset path")
    if relative.as_posix() not in context.referenced_assets:
        raise Light2DContractError("Light2D asset is not referenced")
    return _resolve_contained_file(context.renderer_root, relative)


@contextmanager
def open_referenced_asset(
    context: Light2DRendererContext,
    asset_path: object,
) -> Iterator[BinaryIO]:
    relative = safe_relative_path(asset_path, suffix=".png")
    if relative is None:
        raise Light2DContractError("invalid Light2D asset path")
    if relative.as_posix() not in context.referenced_assets:
        raise Light2DContractError("Light2D asset is not referenced")
    with _open_file_no_follow(context.renderer_root, relative) as opened:
        yield opened


def normalize_pcm16(samples: np.ndarray) -> np.ndarray:
    pcm = np.asarray(samples)
    if pcm.ndim != 1 or pcm.dtype != np.int16:
        raise ValueError("Light2D PCM must be a one-dimensional int16 array")
    return pcm.astype(np.float64) / 32768.0


def mouth_state_for_energy(
    energy: float,
    thresholds: Mapping[str, float],
) -> MouthState:
    if energy < thresholds["silence_gate"]:
        return "closed"
    if energy < thresholds["small_threshold"]:
        return "small"
    if energy < thresholds["medium_threshold"]:
        return "medium"
    return "large"


def _rgba_source_over(destination: np.ndarray, source: np.ndarray, alpha: float) -> np.ndarray:
    if alpha <= 0:
        return destination
    src = source.astype(np.float32) / 255.0
    dst = destination.astype(np.float32) / 255.0
    source_alpha = src[..., 3:4] * min(1.0, alpha)
    destination_alpha = dst[..., 3:4]
    output_alpha = source_alpha + destination_alpha * (1.0 - source_alpha)
    premultiplied = (
        src[..., :3] * source_alpha
        + dst[..., :3] * destination_alpha * (1.0 - source_alpha)
    )
    output_rgb = np.divide(
        premultiplied,
        output_alpha,
        out=np.zeros_like(premultiplied),
        where=output_alpha > 0,
    )
    output = np.concatenate((output_rgb, output_alpha), axis=2)
    return np.rint(np.clip(output, 0.0, 1.0) * 255.0).astype(np.uint8)


class Light2DRenderer:
    def __init__(
        self,
        context: Light2DRendererContext,
        *,
        sample_rate: int = DEFAULT_LIGHT2D_SAMPLE_RATE,
        fps: int = DEFAULT_LIGHT2D_FPS,
    ) -> None:
        if sample_rate <= 0 or fps <= 0:
            raise ValueError("Light2D sample rate and FPS must be positive")
        self.context = context
        self.sample_rate = sample_rate
        self.fps = fps
        self._base = self._load_layer(context.config["layers"]["base"])
        self._blink = self._load_layer(context.config["layers"]["blink"])
        self._mouth = {
            state: self._load_layer(context.config["layers"]["mouth"][state])
            for state in ("closed", "small", "medium", "large")
        }

    def _load_layer(self, entry: Mapping[str, Any]) -> _PreloadedLayer:
        try:
            with open_referenced_asset(self.context, entry["source"]) as opened:
                with Image.open(opened) as image:
                    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        except (OSError, UnidentifiedImageError) as exc:
            raise Light2DContractError("invalid Light2D PNG asset") from exc
        x, y, width, height = (int(value) for value in entry["rect"])
        if rgba.shape[:2] != (height, width):
            resampling = getattr(Image, "Resampling", Image).BILINEAR
            rgba = np.asarray(
                Image.fromarray(rgba, "RGBA").resize((width, height), resampling),
                dtype=np.uint8,
            ).copy()
        return _PreloadedLayer(rgba=rgba, rect=(x, y, width, height))

    def _draw_layer(
        self,
        canvas: np.ndarray,
        layer: _PreloadedLayer,
        alpha: float = 1.0,
    ) -> None:
        x, y, width, height = layer.rect
        canvas[y : y + height, x : x + width] = _rgba_source_over(
            canvas[y : y + height, x : x + width],
            layer.rgba,
            alpha,
        )

    def render_rgba(self, state: Light2DFrameState) -> np.ndarray:
        canvas_config = self.context.config["canvas"]
        canvas_shape = (canvas_config["height"], canvas_config["width"], 4)
        if self._base.rect == (0, 0, canvas_config["width"], canvas_config["height"]):
            canvas = self._base.rgba.copy()
        else:
            canvas = np.zeros(canvas_shape, dtype=np.uint8)
            self._draw_layer(canvas, self._base)
        if state.mouth_progress < 1 and state.previous_mouth_state != state.mouth_state:
            self._draw_layer(
                canvas,
                self._mouth[state.previous_mouth_state],
                1.0 - state.mouth_progress,
            )
        current_alpha = (
            1.0
            if state.previous_mouth_state == state.mouth_state
            else state.mouth_progress
        )
        self._draw_layer(canvas, self._mouth[state.mouth_state], current_alpha)
        if state.blinking:
            self._draw_layer(canvas, self._blink)
        return self._apply_transform(canvas, state.transforms)

    @staticmethod
    def _apply_transform(canvas: np.ndarray, transforms: Light2DTransforms) -> np.ndarray:
        if transforms.scale_y == 1.0 and transforms.rotation_degrees == 0.0:
            return canvas
        height, width = canvas.shape[:2]
        pivot_x = width / 2.0
        pivot_y = float(height)
        radians = math.radians(transforms.rotation_degrees)
        cosine = math.cos(radians)
        sine = math.sin(radians)
        scale_y = transforms.scale_y
        matrix = np.asarray(
            [
                [cosine, -sine * scale_y, pivot_x - cosine * pivot_x + sine * scale_y * pivot_y],
                [sine, cosine * scale_y, pivot_y - sine * pivot_x - cosine * scale_y * pivot_y],
            ],
            dtype=np.float32,
        )
        opaque = bool(np.all(canvas[..., 3] == 255))
        if opaque:
            premultiplied: np.ndarray = canvas
        else:
            premultiplied = canvas.astype(np.float32) / 255.0
            premultiplied[..., :3] *= premultiplied[..., 3:4]
        warped = cv2.warpAffine(
            premultiplied,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        if opaque:
            warped_float = warped.astype(np.float32) / 255.0
        else:
            warped_float = warped.astype(np.float32, copy=False)
        alpha = warped_float[..., 3:4]
        straight_rgb = np.divide(
            warped_float[..., :3],
            alpha,
            out=np.zeros_like(warped_float[..., :3]),
            where=alpha > 0,
        )
        straight = np.concatenate((straight_rgb, alpha), axis=2)
        return np.rint(np.clip(straight, 0.0, 1.0) * 255.0).astype(np.uint8)

    def iter_frames(
        self,
        pcm: np.ndarray,
        *,
        sample_rate: int | None = None,
        fps: int | None = None,
    ) -> Iterator[Light2DRenderedFrame]:
        normalized = normalize_pcm16(pcm)
        render_sample_rate = self.sample_rate if sample_rate is None else sample_rate
        render_fps = self.fps if fps is None else fps
        if render_sample_rate <= 0 or render_fps <= 0:
            raise ValueError("Light2D sample rate and FPS must be positive")
        frame_count = max(1, math.ceil(len(normalized) * render_fps / render_sample_rate))
        delta_ms = 1000.0 / render_fps
        audio = self.context.config["audio"]
        animation = self.context.config["animation"]
        energy = 0.0
        current_mouth: MouthState = "closed"
        previous_mouth: MouthState = "closed"
        mouth_changed_at = 0.0

        for frame_index in range(frame_count):
            timestamp_ms = frame_index * delta_ms
            start = math.floor(frame_index * render_sample_rate / render_fps)
            end = math.floor((frame_index + 1) * render_sample_rate / render_fps)
            window_size = max(1, end - start)
            window = np.zeros(window_size, dtype=np.float64)
            available = normalized[start : min(end, len(normalized))]
            window[: len(available)] = available
            raw_energy = math.sqrt(float(np.mean(np.square(window, dtype=np.float64))))
            target_energy = 0.0 if raw_energy < audio["silence_gate"] else raw_energy
            duration = audio["attack_ms"] if target_energy > energy else audio["release_ms"]
            alpha = 1.0 - math.exp(-delta_ms / max(1.0, duration))
            energy += (max(0.0, target_energy) - energy) * alpha
            next_mouth = mouth_state_for_energy(energy, audio)
            if next_mouth != current_mouth:
                previous_mouth = current_mouth
                current_mouth = next_mouth
                mouth_changed_at = timestamp_ms
            mouth_progress = min(1.0, (timestamp_ms - mouth_changed_at) / audio["crossfade_ms"])
            breath_phase = (timestamp_ms % animation["breath_period_ms"]) / animation[
                "breath_period_ms"
            ]
            sway_phase = breath_phase * math.tau
            breath_scale = math.sin(sway_phase) * animation["breath_scale"]
            sway_degrees = math.sin(sway_phase * 0.75) * animation["sway_degrees"]
            speaking_weight = min(1.0, energy / max(audio["medium_threshold"], 0.001))
            transforms = Light2DTransforms(
                breath_scale=breath_scale,
                sway_degrees=sway_degrees,
                speaking_weight=speaking_weight,
                scale_y=1.0 + breath_scale + speaking_weight * 0.003,
                rotation_degrees=sway_degrees + speaking_weight * 0.12,
            )
            blink_local = timestamp_ms % animation["blink_period_ms"]
            state = Light2DFrameState(
                timestamp_ms=timestamp_ms,
                raw_energy=raw_energy,
                energy=energy,
                mouth_state=current_mouth,
                previous_mouth_state=previous_mouth,
                mouth_progress=mouth_progress,
                blinking=blink_local < animation["blink_duration_ms"],
                transforms=transforms,
            )
            yield Light2DRenderedFrame(rgba=self.render_rgba(state), state=state)
