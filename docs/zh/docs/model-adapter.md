# 模型适配器

模型适配器是 OpenTalking 流水线与 talking-head 模型之间的集成点。适配器接收音频片段，
输出视频帧。

本页说明本地 adapter、backend resolver，以及新增合成模型的推荐接入路径。

## `ModelAdapter` 协议

源码：`opentalking/core/interfaces/model_adapter.py`。

```python
from typing import Any, Protocol, runtime_checkable
from opentalking.core.types.frames import AudioChunk, VideoFrameData


@runtime_checkable
class ModelAdapter(Protocol):
    @property
    def model_type(self) -> str: ...

    def load_model(self, device: str = "cuda") -> None:
        """加载模型权重至指定设备。"""

    def load_avatar(self, avatar_path: str) -> Any:
        """加载 Avatar 资产，返回模型自定义的不透明状态对象。"""

    def warmup(self) -> None:
        """执行一次空推理，避免首次真实调用的高延迟。"""

    def extract_features(self, audio_chunk: AudioChunk) -> Any:
        """从音频片段计算驱动特征。"""

    def infer(self, features: Any, avatar_state: Any) -> list[Any]:
        """执行推理，返回逐步预测。"""

    def compose_frame(
        self, avatar_state: Any, frame_idx: int, prediction: Any
    ) -> VideoFrameData:
        """根据预测与 Avatar 状态合成完整视频帧。"""

    def idle_frame(self, avatar_state: Any, frame_idx: int) -> VideoFrameData:
        """无语音时返回帧（循环或保持最后一帧）。"""
```

适配器类型定义为 Protocol，而非抽象基类；任何匹配方法签名的类型均可被接受。
`runtime_checkable` 装饰器使 `isinstance` 运行时检查可用。

## 注册

源码：`opentalking/models/registry.py`。

```python
from opentalking.models.registry import register_model

@register_model("my-model")
class MyAdapter:
    @property
    def model_type(self) -> str:
        return "my-model"
    # 后续协议方法略。
```

装饰器将工厂函数存入模块级注册表。每次调用 `get_adapter("my-model")` 返回新实例。
注册在 import 时完成，由 `ensure_models_imported()` 在首次查找时触发。

新增本地适配器的接入步骤：

1. 将类置于 `opentalking/models/<name>/adapter.py`。
2. 在 `opentalking/models/registry.py` 的 `ensure_models_imported()` 中 import 该模块。
3. 在 YAML 中设置 `models.<name>.backend: local`，或设置
   `OPENTALKING_<NAME>_BACKEND=local`。
4. 重启服务。`GET /models` 响应中会包含 `backend: local`；只有 adapter 可正常 import
   时才会显示 `connected=true`。

## Backend resolver

OpenTalking 不假设所有真实模型都必须运行在 OmniRT 上。创建会话时，流水线通过
`opentalking/providers/synthesis/backends.py` 根据 `model + backend` 解析运行入口：

| backend | 运行路径 | 可用性规则 |
|---------|----------|------------|
| `mock` | 内置 mock 合成 client。 | 始终 connected。 |
| `local` | 从 `opentalking/models/<name>/` 加载 `ModelAdapter`。 | `get_adapter(name)` 成功时 connected。 |
| `direct_ws` | YAML 或 settings 中配置的模型专属 WebSocket URL。 | 配置了 WebSocket URL 时 connected。 |
| `omnirt` | 配置的 OmniRT 端点上的 `/v1/audio2video/{model}`。 | OmniRT 模型列表包含该模型时 connected。 |

默认 backend 优先保持兼容：

```yaml
models:
  wav2lip: { backend: omnirt }
  musetalk: { backend: omnirt }
  flashtalk: { backend: omnirt }
  flashhead: { backend: direct_ws }
  quicktalk: { backend: local }
  mock: { backend: mock }
```

可通过 `OPENTALKING_<MODEL>_BACKEND` 在运行时覆盖 YAML。例如
`OPENTALKING_WAV2LIP_BACKEND=local` 会让 Wav2Lip 使用本地 adapter；如果 adapter
不存在，`/models` 将返回 `connected=false` 与 `reason=local_adapter_missing`，会话
创建会明确失败，而不是静默回退 OmniRT。

## 参考实现：echo 适配器

下述适配器输出与输入音频振幅成正比的灰度帧，可作为最小模板。

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
        return [features] * 25  # 25 帧对应 1 秒音频片段（25 FPS）

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

注册适配器：

```python title="opentalking/models/registry.py（diff）"
def ensure_models_imported() -> None:
    import opentalking.models.quicktalk.adapter  # noqa: F401
    import opentalking.models.echo.adapter       # noqa: F401  # 新增
```

构造匹配的 avatar manifest：

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

重启服务后，在前端选择 `echo-demo` avatar 与 `echo` 模型。输出帧亮度随输入音频振幅
变化。

## 参考实现：QuickTalk 适配器

生产级示例位于 `opentalking/models/quicktalk/`：

- `adapter.py` —— 实现协议，并将工作委托给 `QuickTalkRuntime`。
- `runtime.py` —— V1 运行时，包含进程内推理与面部缓存。
- `runtime_v2.py` —— V2 运行时，将推理委托给外部 Worker 进程。

适配器与运行时分离是推荐模式：适配器处理协议事务，运行时处理模型加载与推理细节。

## 远端与直连 backend

远端模型应接入 `opentalking/providers/synthesis/`，而不是伪装成本地 adapter。经验规则：

| 模型形态 | 推荐 backend |
|----------|--------------|
| 进程内轻量运行时 | `local` |
| 一个模型对应一个 WebSocket 端点 | `direct_ws` |
| 重模型、多卡调度、GPU/NPU 远端部署 | `omnirt` |
| 测试或 CI 占位 | `mock` |

FlashTalk 保留 legacy WebSocket 兼容路径：当 backend 为 `omnirt` 但未配置
`OMNIRT_ENDPOINT` 时，可用 `OPENTALKING_FLASHTALK_WS_URL` 标记为 `legacy_ws`。
新的远端集成应优先显式使用 `backend: direct_ws` 或 `backend: omnirt`。

## 源文件

| 文件 | 职责 |
|------|------|
| `opentalking/core/interfaces/model_adapter.py` | `ModelAdapter` 协议定义。 |
| `opentalking/core/types/frames.py` | `AudioChunk` 与 `VideoFrameData` 类型。 |
| `opentalking/core/model_config.py` | 每模型 backend 默认值、YAML 覆盖与 `OPENTALKING_<MODEL>_BACKEND`。 |
| `opentalking/models/registry.py` | `@register_model`、`get_adapter`、`list_models`。 |
| `opentalking/models/quicktalk/` | 本地适配器参考实现。 |
| `opentalking/providers/synthesis/backends.py` | 为模型解析所选 backend 与 direct WebSocket URL。 |
| `opentalking/providers/synthesis/availability.py` | 根据当前环境解析可用模型集合。 |
