from __future__ import annotations

import io
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

from opentalking.core.types.frames import AudioChunk
from opentalking.media.frame_avatar import FrameAvatarState
from opentalking.models.wav2lip.adapter import Wav2LipAdapter, Wav2LipPrediction


def _install_fake_wav2lip_runtime(monkeypatch) -> type:
    runtime_mod = types.ModuleType("opentalking.models.wav2lip.runtime")
    loader_mod = types.ModuleType("opentalking.models.wav2lip.loader")
    realtime_mod = types.ModuleType("opentalking.models.wav2lip.realtime")

    class AvatarAudioSpec:
        def __init__(self, sample_rate=16000, channels=1, chunk_samples=14933):
            self.sample_rate = sample_rate
            self.channels = channels
            self.chunk_samples = chunk_samples

    class AvatarVideoSpec:
        def __init__(
            self,
            fps=25,
            width=416,
            height=704,
            frame_count=29,
            motion_frames_num=1,
            slice_len=28,
        ):
            self.fps = fps
            self.width = width
            self.height = height
            self.frame_count = frame_count
            self.motion_frames_num = motion_frames_num
            self.slice_len = slice_len

    class RealtimeAvatarSession:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class RealtimeAvatarService:
        def __init__(self, *, runtime=None, allowed_frame_roots=None):
            self.runtime = runtime
            self.allowed_frame_roots = allowed_frame_roots
            self.created = []

        def create_session(self, *, model, backend, image_bytes, prompt="", config=None):
            config = dict(config or {})
            width = int(config.get("width", 416))
            height = int(config.get("height", 704))
            raw_max_long_edge = (
                __import__("os").environ.get("OPENTALKING_WAV2LIP_MAX_LONG_EDGE")
                or __import__("os").environ.get("OMNIRT_WAV2LIP_MAX_LONG_EDGE")
                or "832"
            )
            max_long_edge = int(raw_max_long_edge or "0")
            if model == "wav2lip" and max_long_edge > 0 and max(width, height) > max_long_edge:
                scale = max_long_edge / float(max(width, height))
                width = max(2, int(round(width * scale)))
                height = max(2, int(round(height * scale)))
                width -= width % 2
                height -= height % 2
            session = RealtimeAvatarSession(
                session_id="fake_session",
                trace_id="fake_trace",
                model=model,
                backend=backend,
                prompt=prompt,
                image_bytes=image_bytes,
                reference_mode=config.get("reference_mode", "image"),
                ref_frame_dir=config.get("ref_frame_dir"),
                ref_frame_metadata_path=config.get("ref_frame_metadata_path"),
                audio=AvatarAudioSpec(
                    sample_rate=int(config.get("sample_rate", 16000)),
                    channels=1,
                    chunk_samples=28 * int(config.get("sample_rate", 16000)) // int(config.get("fps", 25)),
                ),
                video=AvatarVideoSpec(
                    fps=int(config.get("fps", 25)),
                    width=width,
                    height=height,
                    frame_count=29,
                    motion_frames_num=1,
                    slice_len=28,
                ),
                wav2lip_postprocess_mode=config.get("wav2lip_postprocess_mode", "easy_improved"),
                preprocessed=bool(config.get("preprocessed")),
                mouth_metadata=config.get("mouth_metadata", {}),
            )
            self.created.append(session)
            return session

    def encode_jpeg_sequence(jpeg_frames):
        payload = bytearray(b"VIDX")
        payload.extend(len(jpeg_frames).to_bytes(4, "little"))
        for frame in jpeg_frames:
            payload.extend(len(frame).to_bytes(4, "little"))
            payload.extend(frame)
        return bytes(payload)

    def decode_jpeg_sequence(payload):
        assert payload[:4] == b"VIDX"
        count = int.from_bytes(payload[4:8], "little")
        offset = 8
        frames = []
        for _ in range(count):
            size = int.from_bytes(payload[offset : offset + 4], "little")
            offset += 4
            frames.append(payload[offset : offset + size])
            offset += size
        return frames

    class Prepared:
        def __init__(self, frame):
            self.base_frame = frame

    class State:
        def __init__(self, frame):
            self.frame = frame
            self.emitted_frames = 0
            self.pcm_history = None

        def frame_at(self, _index):
            return Prepared(self.frame)

    class Wav2LipRealtimeRuntime:
        instances = []

        def __init__(self, device="cpu"):
            self.device = device
            self.models_dir = Path(
                __import__("os").environ.get("OPENTALKING_WAV2LIP_MODEL_ROOT", "./models/wav2lip")
            )
            self.checkpoint = self.models_dir / "wav2lip384.pth"
            self.sessions = []
            self.rendered = []
            self.states = {}
            Wav2LipRealtimeRuntime.instances.append(self)

        def _session_state(self, session):
            self.sessions.append(session)
            if session.session_id not in self.states:
                frame = np.zeros((session.video.height, session.video.width, 3), dtype=np.uint8)
                self.states[session.session_id] = State(frame)
            return self.states[session.session_id]

        def render_chunk(self, session, pcm_s16le):
            self.rendered.append((session, pcm_s16le))
            frames = []
            for value in (32, 96):
                image = Image.new("RGB", (session.video.width, session.video.height), (value, 8, 4))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG")
                frames.append(buffer.getvalue())
            return encode_jpeg_sequence(frames)

    realtime_mod.AvatarAudioSpec = AvatarAudioSpec
    realtime_mod.AvatarVideoSpec = AvatarVideoSpec
    realtime_mod.RealtimeAvatarSession = RealtimeAvatarSession
    realtime_mod.RealtimeAvatarService = RealtimeAvatarService
    realtime_mod.decode_jpeg_sequence = decode_jpeg_sequence
    runtime_mod.Wav2LipRealtimeRuntime = Wav2LipRealtimeRuntime
    def resolve_wav2lip_checkpoint(_models_dir):
        if __import__("os").environ.get("OPENTALKING_WAV2LIP_MODEL_ROOT"):
            return Path(__file__).resolve()
        return None

    loader_mod.resolve_wav2lip_checkpoint = resolve_wav2lip_checkpoint
    loader_mod.resolve_wav2lip_s3fd = resolve_wav2lip_checkpoint
    loader_mod._resolve_torch_device = lambda _torch, device: device

    monkeypatch.setitem(sys.modules, "opentalking.models.wav2lip.runtime", runtime_mod)
    monkeypatch.setitem(sys.modules, "opentalking.models.wav2lip.loader", loader_mod)
    monkeypatch.setitem(sys.modules, "opentalking.models.wav2lip.realtime", realtime_mod)
    return Wav2LipRealtimeRuntime


def test_wav2lip_adapter_uses_local_runtime_and_preprocessed_metadata(monkeypatch) -> None:
    fake_runtime = _install_fake_wav2lip_runtime(monkeypatch)
    models_dir = Path(__file__).resolve().parents[2] / "models" / "wav2lip"
    monkeypatch.setenv("OPENTALKING_WAV2LIP_MODEL_ROOT", str(models_dir))
    monkeypatch.setenv("OPENTALKING_WAV2LIP_MAX_LONG_EDGE", "768")
    root = Path(__file__).resolve().parents[2]
    adapter = Wav2LipAdapter()
    adapter.load_model("cpu")
    state = adapter.load_avatar(str(root / "examples" / "avatars" / "singer"))

    assert not isinstance(state, FrameAvatarState)
    session = fake_runtime.instances[-1].sessions[-1]
    assert session.reference_mode == "frames"
    assert session.preprocessed is True
    assert Path(session.ref_frame_dir).parts[-4:] == ("examples", "avatars", "singer", "frames")
    assert Path(session.ref_frame_metadata_path).parts[-5:] == (
        "examples",
        "avatars",
        "singer",
        "frames",
        "mouth_metadata.json",
    )
    assert session.wav2lip_postprocess_mode == "easy_improved"
    assert session.video.width == 574
    assert session.video.height == 768
    assert session.video.fps == 30

    chunk = AudioChunk(
        data=np.full(1600, 2400, dtype=np.int16),
        sample_rate=16000,
        duration_ms=100.0,
    )
    features = adapter.extract_features_for_stream(chunk, state)
    predictions = adapter.infer(features, state)

    assert fake_runtime.instances[-1].rendered[-1][1] == chunk.data.tobytes()
    assert len(predictions) == 2
    assert all(isinstance(item, Wav2LipPrediction) for item in predictions)

    frame = adapter.compose_frame(state, 0, predictions[0])

    assert frame.width == session.video.width
    assert frame.height == session.video.height
    assert frame.data.shape[:2] == (session.video.height, session.video.width)


def test_wav2lip_adapter_uses_omnirt_resolution_limit_by_default(monkeypatch) -> None:
    fake_runtime = _install_fake_wav2lip_runtime(monkeypatch)
    models_dir = Path(__file__).resolve().parents[2] / "models" / "wav2lip"
    monkeypatch.setenv("OPENTALKING_WAV2LIP_MODEL_ROOT", str(models_dir))
    monkeypatch.delenv("OPENTALKING_WAV2LIP_MAX_LONG_EDGE", raising=False)
    monkeypatch.delenv("OMNIRT_WAV2LIP_MAX_LONG_EDGE", raising=False)
    root = Path(__file__).resolve().parents[2]
    adapter = Wav2LipAdapter()
    adapter.load_model("cpu")

    adapter.load_avatar(str(root / "examples" / "avatars" / "singer"))

    session = fake_runtime.instances[-1].sessions[-1]
    assert session.video.width == 622
    assert session.video.height == 832


def test_wav2lip_adapter_postprocess_override_wins_over_manifest_and_env(monkeypatch) -> None:
    fake_runtime = _install_fake_wav2lip_runtime(monkeypatch)
    models_dir = Path(__file__).resolve().parents[2] / "models" / "wav2lip"
    monkeypatch.setenv("OPENTALKING_WAV2LIP_MODEL_ROOT", str(models_dir))
    monkeypatch.setenv("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")
    root = Path(__file__).resolve().parents[2]
    adapter = Wav2LipAdapter()
    adapter.set_wav2lip_postprocess_mode("basic")
    adapter.load_model("cpu")

    adapter.load_avatar(str(root / "examples" / "avatars" / "singer"))

    session = fake_runtime.instances[-1].sessions[-1]
    assert session.wav2lip_postprocess_mode == "basic"


def test_wav2lip_adapter_warmup_runs_runtime_forward_and_restores_stream_state(monkeypatch) -> None:
    fake_runtime = _install_fake_wav2lip_runtime(monkeypatch)
    models_dir = Path(__file__).resolve().parents[2] / "models" / "wav2lip"
    monkeypatch.setenv("OPENTALKING_WAV2LIP_MODEL_ROOT", str(models_dir))
    root = Path(__file__).resolve().parents[2]
    adapter = Wav2LipAdapter()
    adapter.load_model("cpu")
    state = adapter.load_avatar(str(root / "examples" / "avatars" / "anchor"))
    runtime = fake_runtime.instances[-1]
    runtime.rendered.clear()
    state.emitted_frames = 7
    runtime_state = runtime._session_state(state.session)
    runtime_state.pcm_history = np.full(12, 99, dtype=np.int16)
    runtime_state.emitted_frames = 5

    adapter.warmup(state)

    assert len(runtime.rendered) == 1
    assert np.frombuffer(runtime.rendered[0][1], dtype=np.int16).size >= 3200
    assert state.emitted_frames == 7
    assert runtime_state.emitted_frames == 5
    np.testing.assert_array_equal(runtime_state.pcm_history, np.full(12, 99, dtype=np.int16))


def test_wav2lip_adapter_accepts_reference_only_avatar_with_local_runtime(monkeypatch) -> None:
    _install_fake_wav2lip_runtime(monkeypatch)
    models_dir = Path(__file__).resolve().parents[2] / "models" / "wav2lip"
    monkeypatch.setenv("OPENTALKING_WAV2LIP_MODEL_ROOT", str(models_dir))
    root = Path(__file__).resolve().parents[2]
    adapter = Wav2LipAdapter()
    adapter.load_model("cpu")
    state = adapter.load_avatar(str(root / "examples" / "avatars" / "anchor"))

    assert not isinstance(state, FrameAvatarState)
    assert state.session.reference_mode == "image"

    chunk = AudioChunk(
        data=np.zeros(1600, dtype=np.int16),
        sample_rate=16000,
        duration_ms=100.0,
    )
    features = adapter.extract_features_for_stream(chunk, state)
    prediction = adapter.infer(features, state)[0]
    frame = adapter.compose_frame(state, 0, prediction)

    assert frame.width == state.manifest.width
    assert frame.height == state.manifest.height


def test_wav2lip_adapter_legacy_fallback_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("OPENTALKING_WAV2LIP_LEGACY_LOCAL_FALLBACK", "1")
    root = Path(__file__).resolve().parents[2]
    adapter = Wav2LipAdapter()
    state = adapter.load_avatar(str(root / "examples" / "avatars" / "singer"))

    assert isinstance(state, FrameAvatarState)
    assert state.frames


def test_wav2lip_runtime_available_uses_opentalking_model_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_fake_wav2lip_runtime(monkeypatch)
    models_dir = tmp_path / "models"
    (models_dir / "wav2lip").mkdir(parents=True)
    (models_dir / "wav2lip" / "wav2lip384.pth").write_bytes(b"ckpt")
    (models_dir / "wav2lip" / "s3fd.pth").write_bytes(b"s3fd")

    monkeypatch.setenv("OPENTALKING_WAV2LIP_MODEL_ROOT", str(models_dir / "wav2lip"))

    assert Wav2LipAdapter.runtime_available() is True


def test_wav2lip_runtime_available_ignores_legacy_omnirt_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_fake_wav2lip_runtime(monkeypatch)
    legacy_models_dir = tmp_path / "legacy_models"
    (legacy_models_dir / "wav2lip").mkdir(parents=True)
    (legacy_models_dir / "wav2lip" / "wav2lip384.pth").write_bytes(b"ckpt")
    (legacy_models_dir / "wav2lip" / "s3fd.pth").write_bytes(b"s3fd")

    monkeypatch.setenv("OMNIRT_WAV2LIP_MODELS_DIR", str(legacy_models_dir))
    monkeypatch.setenv("OMNIRT_WAV2LIP_DEVICE", "cpu")
    monkeypatch.delenv("OPENTALKING_WAV2LIP_MODEL_ROOT", raising=False)
    monkeypatch.delenv("OPENTALKING_WAV2LIP_DEVICE", raising=False)

    assert Wav2LipAdapter.runtime_available() is False
