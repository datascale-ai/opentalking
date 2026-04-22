# 模型适配器

## 注册机制

普通视觉模型通过 `src/opentalking/models/registry.py` 注册:

```python
@register_model("wav2lip")
class Wav2LipAdapter:
    ...
```

仓库启动时 `opentalking.models.__init__` 会执行 `ensure_models_imported()`，因此内置的:

- `wav2lip`
- `musetalk`

会自动进入注册表。

## `ModelAdapter` 协议

定义位置:

`src/opentalking/core/interfaces/model_adapter.py`

当前协议包含:

| 方法 | 作用 |
|------|------|
| `model_type` | 模型类型字符串 |
| `load_model(device)` | 加载模型权重 |
| `load_avatar(path)` | 读取头像资产，返回模型私有状态 |
| `warmup()` | 首次推理预热 |
| `extract_features(audio_chunk)` | 从音频块提取驱动特征 |
| `infer(features, avatar_state)` | 产生逐帧预测 |
| `compose_frame(avatar_state, frame_idx, prediction)` | 生成最终视频帧 |
| `idle_frame(avatar_state, frame_idx)` | 非播报时的空闲帧 |

## 运行时扩展点

虽然协议本身很小，当前渲染流水线还会探测一些可选能力:

- `extract_features_for_stream(...)`
- avatar `extra` 里的流式上下文
- overlap frame 状态

如果你需要更细的流式控制，可以参考:

- `MuseTalkAdapter`
- `Wav2LipAdapter`
- `worker/pipeline/render_pipeline.py`

## FlashTalk 不是普通 `ModelAdapter`

`flashtalk` 当前是特例:

- 不走 `get_adapter("flashtalk")`
- 不在 `_ADAPTERS` 中注册
- 由 `worker/task_consumer.py` 根据 `model == "flashtalk"` 直接创建 `FlashTalkRunner`

原因是它不仅是视觉模型，还自带了完整的 LLM / TTS / 远端推理协议。

## 新增一个模型的最小步骤

1. 在 `src/opentalking/models/<your_model>/` 下实现适配器
2. 使用 `@register_model("<name>")`
3. 让 `src/opentalking/models/registry.py` 的导入流程能触发它
4. 准备与之匹配的头像资产格式
5. 确认 `/models` 可以列出它

## 头像状态建议

建议把模型专用的中间状态放进 `avatar_state.extra`，例如:

- 预处理坐标
- 上一 chunk 的特征尾部
- 手势状态
- 流式平滑参数

当前 `render_pipeline.py` 已经在依赖这种模式。
