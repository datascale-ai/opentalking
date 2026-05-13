# Model Adapter

A model adapter is the integration point between OpenTalking's pipeline and a
talking-head model. The adapter receives audio chunks and produces video frames.

This page documents local adapters, the backend resolver, and the recommended
integration path for adding a synthesis model.

## The `ModelAdapter` protocol

Source: `opentalking/core/interfaces/model_adapter.py`.

```python
from typing import Any, Protocol, runtime_checkable
from opentalking.core.types.frames import AudioChunk, VideoFrameData


@runtime_checkable
class ModelAdapter(Protocol):
    @property
    def model_type(self) -> str: ...

    def load_model(self, device: str = "cuda") -> None:
        """Load model weights onto the specified device."""

    def load_avatar(self, avatar_path: str) -> Any:
        """Load avatar assets and return an opaque model-specific state object."""

    def warmup(self) -> None:
        """Perform a dummy inference to amortize first-call latency."""

    def extract_features(self, audio_chunk: AudioChunk) -> Any:
        """Compute driving features from an audio chunk."""

    def infer(self, features: Any, avatar_state: Any) -> list[Any]:
        """Run inference. Returns per-step predictions."""

    def compose_frame(
        self, avatar_state: Any, frame_idx: int, prediction: Any
    ) -> VideoFrameData:
        """Compose a complete video frame from a prediction and the avatar state."""

    def idle_frame(self, avatar_state: Any, frame_idx: int) -> VideoFrameData:
        """Return a frame when no audio is being spoken (loop or hold the last frame)."""
```

Adapters are typed as protocols rather than abstract base classes; any class matching
the method signatures is accepted. The `runtime_checkable` decorator enables
`isinstance` checks at runtime.

## Registration

Source: `opentalking/models/registry.py`.

```python
from opentalking.models.registry import register_model

@register_model("my-model")
class MyAdapter:
    @property
    def model_type(self) -> str:
        return "my-model"
    # Remaining protocol methods follow.
```

The decorator stores a factory in a module-level registry. `get_adapter("my-model")`
returns a new instance on each call. Registration is performed at import time and is
triggered by `ensure_models_imported()`, which runs on first lookup.

To make a new local adapter discoverable:

1. Place the class in a module under `opentalking/models/<name>/adapter.py`.
2. Import the module from `ensure_models_imported()` in `opentalking/models/registry.py`.
3. Set `models.<name>.backend: local` in YAML or `OPENTALKING_<NAME>_BACKEND=local`.
4. Restart the server. The new model appears in the `GET /models` response with
   `backend: local`; it is `connected=true` only after the adapter imports cleanly.

## Backend resolver

OpenTalking does not assume that every real model runs on OmniRT. At session creation,
the pipeline resolves `model + backend` through `opentalking/providers/synthesis/backends.py`:

| backend | Runtime path | Availability rule |
|---------|--------------|-------------------|
| `mock` | Built-in mock synthesis client. | Always connected. |
| `local` | `ModelAdapter` loaded from `opentalking/models/<name>/`. | Connected when `get_adapter(name)` succeeds. |
| `direct_ws` | Model-specific WebSocket URL from YAML or settings. | Connected when a WebSocket URL is configured. |
| `omnirt` | `/v1/audio2video/{model}` on the configured OmniRT endpoint. | Connected when OmniRT reports the model. |

Default backends are compatibility-oriented:

```yaml
models:
  wav2lip: { backend: omnirt }
  musetalk: { backend: omnirt }
  flashtalk: { backend: omnirt }
  flashhead: { backend: direct_ws }
  quicktalk: { backend: local }
  mock: { backend: mock }
```

Use `OPENTALKING_<MODEL>_BACKEND` to override the YAML value at runtime. For example,
`OPENTALKING_WAV2LIP_BACKEND=local` makes Wav2Lip use a local adapter; if that adapter
is not present, `/models` returns `connected=false` with `reason=local_adapter_missing`
and session creation fails clearly instead of falling back to OmniRT.

## Reference implementation: an echo adapter

The following adapter produces a frame whose brightness is proportional to the audio
energy. It serves as a minimal template.

```python title="opentalking/models/echo/adapter.py"
from __future__ import annotations
from pathlib import Path
from typing import Any
import numpy as np

from opentalking.core.interfaces.model_adapter import ModelAdapter
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.models.registry import register_model


@register_model("echo")
class EchoAdapter:
    def __init__(self) -> None:
        self._device = "cpu"

    @property
    def model_type(self) -> str:
        return "echo"

    def load_model(self, device: str = "cuda") -> None:
        self._device = device

    def load_avatar(self, avatar_path: str) -> dict[str, Any]:
        import json
        manifest = json.loads(Path(avatar_path, "manifest.json").read_text())
        return {"w": manifest["width"], "h": manifest["height"]}

    def warmup(self) -> None:
        return None

    def extract_features(self, audio_chunk: AudioChunk) -> int:
        return int(np.abs(audio_chunk.samples).mean() * 1000)

    def infer(self, features: int, avatar_state: dict[str, Any]) -> list[int]:
        return [features] * 25  # 25 frames per 1-second chunk at 25 FPS

    def compose_frame(
        self, avatar_state: dict[str, Any], frame_idx: int, prediction: int
    ) -> VideoFrameData:
        h, w = avatar_state["h"], avatar_state["w"]
        rgb = np.full((h, w, 3), min(prediction, 255), dtype=np.uint8)
        return VideoFrameData(image=rgb, frame_idx=frame_idx)

    def idle_frame(
        self, avatar_state: dict[str, Any], frame_idx: int
    ) -> VideoFrameData:
        h, w = avatar_state["h"], avatar_state["w"]
        rgb = np.zeros((h, w, 3), dtype=np.uint8)
        return VideoFrameData(image=rgb, frame_idx=frame_idx)
```

Register the adapter:

```python title="opentalking/models/registry.py (diff)"
def ensure_models_imported() -> None:
    import opentalking.models.quicktalk.adapter  # noqa: F401
    import opentalking.models.echo.adapter       # noqa: F401  # added
```

Create a matching avatar manifest:

```json title="examples/avatars/echo-demo/manifest.json"
{
  "id": "echo-demo",
  "name": "Echo",
  "model_type": "echo",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "version": "1.0"
}
```

After restarting the server, select the `echo-demo` avatar and `echo` model in the
frontend. The output frame brightness varies with the input audio amplitude.

## Reference implementation: QuickTalk adapter

A production-quality example resides at `opentalking/models/quicktalk/`:

- `adapter.py` — implements the protocol and delegates to a `QuickTalkRuntime`.
- `runtime.py` — V1 runtime with in-process inference and face cache.
- `runtime_v2.py` — V2 runtime that delegates inference to an external worker process.

Separating the adapter from the runtime is a recommended pattern: the adapter handles
protocol concerns; the runtime handles model loading and inference details.

## Remote and direct backends

Remote models should be integrated under `opentalking/providers/synthesis/`, not as
fake local adapters. Use the following rule of thumb:

| Model shape | Recommended backend |
|-------------|---------------------|
| In-process lightweight runtime | `local` |
| One model, one WebSocket endpoint | `direct_ws` |
| Heavyweight model, multi-card scheduling, GPU/NPU remote deployment | `omnirt` |
| Test-only or CI placeholder | `mock` |

FlashTalk keeps a legacy direct WebSocket fallback for existing deployments:
when its backend is `omnirt` but `OMNIRT_ENDPOINT` is empty, `OPENTALKING_FLASHTALK_WS_URL`
can still mark the model connected as `legacy_ws`. New remote integrations should
prefer explicit `backend: direct_ws` or `backend: omnirt`.

## Source files

| File | Responsibility |
|------|---------------|
| `opentalking/core/interfaces/model_adapter.py` | The `ModelAdapter` protocol definition. |
| `opentalking/core/types/frames.py` | `AudioChunk` and `VideoFrameData` types. |
| `opentalking/core/model_config.py` | Per-model backend defaults, YAML overrides, and `OPENTALKING_<MODEL>_BACKEND`. |
| `opentalking/models/registry.py` | `@register_model`, `get_adapter`, `list_models`. |
| `opentalking/models/quicktalk/` | Reference local adapter implementation. |
| `opentalking/providers/synthesis/backends.py` | Resolves the selected backend and direct WebSocket URL for a model. |
| `opentalking/providers/synthesis/availability.py` | Resolves the set of usable models given the current environment. |
