# FlashTalk

## 什么时候使用 FlashTalk

FlashTalk 适合高质量实时数字人、直播口播、客服数字人和需要更强表现力的场景。它比 Wav2Lip / QuickTalk 更重，建议通过 OmniRT 独立部署，而不是放进 OpenTalking API 进程。

## OpenTalking 与 OmniRT 的边界

OpenTalking 负责 WebUI、会话、TTS、WebRTC、录制和状态管理。FlashTalk 权重加载、GPU 调度和实际推理由 OmniRT 或独立 FlashTalk 服务负责。

## 要求

### GPU

推荐多卡 GPU 或具备足够显存的单卡环境。FlashTalk 对显存、吞吐和服务稳定性要求更高。

### NPU

如果 FlashTalk 后端已在 NPU 上适配，推荐通过 OmniRT 暴露统一 endpoint。OpenTalking 侧不直接管理 NPU runtime。

### 显存 / 内存

显存不足时，优先考虑量化、降低分辨率、减少并发、缩短缓存窗口或拆分模型服务。

### 磁盘

需要放置模型权重、量化权重、临时音视频文件和日志。生产部署建议把模型权重和运行时缓存放在高速磁盘。

## 准备权重

FlashTalk 权重通常放在 OmniRT 服务侧。OpenTalking 默认配置中保留了：

```bash
OPENTALKING_FLASHTALK_CKPT_DIR=./avatar_models/SoulX-FlashTalk-14B
OPENTALKING_FLASHTALK_WAV2VEC_DIR=./avatar_models/chinese-wav2vec2-base
```

实际生产更推荐让 OmniRT 管理这些路径。

## 可调整参数

### 推理质量与延迟

| 配置项 | 环境变量 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `frame_num` | `OPENTALKING_FLASHTALK_FRAME_NUM` | `33` | 每个生成窗口帧数 |
| `motion_frames_num` | `OPENTALKING_FLASHTALK_MOTION_FRAMES_NUM` | `5` | 运动上下文帧数 |
| `sample_steps` | `OPENTALKING_FLASHTALK_SAMPLE_STEPS` | `2` | 采样步数，影响质量和延迟 |
| `sample_shift` | `OPENTALKING_FLASHTALK_SAMPLE_SHIFT` | `5` | 采样偏移 |
| `color_correction_strength` | `OPENTALKING_FLASHTALK_COLOR_CORRECTION_STRENGTH` | `0.0` | 颜色校正强度 |
| `cached_audio_duration` | `OPENTALKING_FLASHTALK_CACHED_AUDIO_DURATION` | `8` | 音频缓存时长 |

### 输出规格

| 配置项 | 环境变量 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `height` | `OPENTALKING_FLASHTALK_HEIGHT` | `704` | 输出高度 |
| `width` | `OPENTALKING_FLASHTALK_WIDTH` | `416` | 输出宽度 |
| `sample_rate` | `OPENTALKING_FLASHTALK_SAMPLE_RATE` | `16000` | 输入音频采样率 |
| `tgt_fps` | `OPENTALKING_FLASHTALK_TGT_FPS` | `25` | 目标 FPS |
| `audio_loudness_norm` | `OPENTALKING_FLASHTALK_AUDIO_LOUDNESS_NORM` | `true` | 是否做音频响度归一 |

### 量化与大模型组件

| 配置项 | 环境变量 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `t5_quant` | `OPENTALKING_FLASHTALK_T5_QUANT` | 空 | T5 量化方式，支持 `int8` / `fp8` |
| `t5_quant_dir` | `OPENTALKING_FLASHTALK_T5_QUANT_DIR` | 空 | T5 量化权重目录 |
| `wan_quant` | `OPENTALKING_FLASHTALK_WAN_QUANT` | 空 | Wan 组件量化方式，支持 `int8` / `fp8` |
| `wan_quant_include` | `OPENTALKING_FLASHTALK_WAN_QUANT_INCLUDE` | 空 | 量化包含规则 |
| `wan_quant_exclude` | `OPENTALKING_FLASHTALK_WAN_QUANT_EXCLUDE` | 空 | 量化排除规则 |

### 队列与会话保护

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_FLASHTALK_MAX_QUEUE_SIZE` | `3` | 等待队列长度，`0` 表示不限制 |
| `OPENTALKING_FLASHTALK_SLOT_TIMEOUT_SEC` | `3600` | 等待 slot 超时 |
| `OPENTALKING_FLASHTALK_MAX_SESSION_SEC` | `600` | 单会话最长占用时间 |

### Idle 与 TTS 边界

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_FLASHTALK_IDLE_ENABLE` | `true` | 是否启用 idle 片段 |
| `OPENTALKING_FLASHTALK_IDLE_SOURCE` | `generated` | idle 来源 |
| `OPENTALKING_FLASHTALK_IDLE_SEED` | `9999` | idle 生成 seed |
| `OPENTALKING_FLASHTALK_TTS_BOUNDARY_FADE_MS` | `18.0` | TTS 边界淡入淡出 |
| `OPENTALKING_FLASHTALK_TTS_COALESCE_MIN_CHARS` | `6` | TTS 合并最小字符数 |
| `OPENTALKING_FLASHTALK_TTS_COALESCE_MAX_CHARS` | `80` | TTS 合并最大字符数 |

## 启动 OmniRT

示例：

```bash
bash scripts/quickstart/start_omnirt_flashtalk.sh
```

具体参数取决于 OmniRT 安装方式、模型权重路径和硬件。

## 配置 OpenTalking

```bash
export OPENTALKING_OMNIRT_ENDPOINT=http://127.0.0.1:9000
export OPENTALKING_FLASHTALK_BACKEND=omnirt
```

## 启动 OpenTalking

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --omnirt http://127.0.0.1:9000
```

## 验证

1. 运行 `bash scripts/quickstart/status.sh`。
2. 确认模型列表包含 `flashtalk`。
3. 在 WebUI 选择 FlashTalk 兼容 Avatar。
4. 发送短文本，观察首帧时间、音频边界和画面稳定性。

## 性能注意事项

- 不建议在同一进程中混跑 API 和 FlashTalk 重模型。
- 生产环境建议限制单会话时长和队列长度。
- TTS 分段策略会影响首帧和连贯性。
- 多模型部署时建议为 FlashTalk 独立 GPU 或独立机器。

## 故障排查

### 模型队列阻塞

检查 slot timeout、max session 和当前活跃会话。生产环境应有明确的会话释放策略。

### 首帧时间过长

检查模型是否冷启动、TTS 是否等待过长、是否存在过大的 `frame_num` 或较重采样配置。

### 显存不足

考虑量化、降低分辨率、减少并发、拆分服务或使用更大显存设备。
