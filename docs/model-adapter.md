# 模型适配器

## 注册

使用 `@register_model("name")` 装饰器，并在包导入时执行注册（参见 `opentalking.models.registry`）。

## `ModelAdapter` 协议（`opentalking.core.interfaces.model_adapter`）

| 方法 | 说明 |
|------|------|
| `load_model(device)` | 加载权重；无文件时可空操作 |
| `load_avatar(path)` | 返回不透明 `avatar_state`（如 `FrameAvatarState`） |
| `warmup()` | 预热 |
| `extract_features(chunk)` | 从 `AudioChunk` 提取驱动特征 |
| `infer(features, avatar_state)` | 返回与当前音频段对齐的预测列表 |
| `compose_frame(avatar_state, frame_idx, prediction)` | 输出一帧 `VideoFrameData` |
| `idle_frame(avatar_state, frame_idx)` | 静默/待机动画帧 |

## 已接入适配器

- `wav2lip`：轻量口型同步 demo / fallback。
- `musetalk`：轻量 talking-head 适配验证。
- `quicktalk`：本地实时 talking-head 适配器，支持流式渲染、Worker 缓存和 `/chat` 对话链路。
- `flashtalk` / `flashhead`：FlashTalk 兼容远端或本地服务路径。

## 接入真实 MuseTalk / Wav2Lip

当前实现包含 **占位推理** 与 **帧循环回退**，便于联调。接入完整网络时：

1. 在 `src/opentalking/models/musetalk/`（或 `wav2lip/`）中加载与 [LiveTalking](https://github.com/lipku/livetalking) 兼容的模块与权重。
2. 在 `infer` / `compose_frame` 中调用真实前向与贴回逻辑。
3. 保持 `extract_features` 输出与 `infer` 输入约定一致（可使用内部 `DrivingFeatures` 等类型）。
