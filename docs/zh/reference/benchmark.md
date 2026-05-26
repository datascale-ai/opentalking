# Benchmark

Benchmark 页面用于说明 OpenTalking 如何记录端到端体验指标，以及如何引用外部模型服务的推理基线。OpenTalking 是编排层，因此这里区分两类数据：

| 类型 | OpenTalking 是否直接负责 | 示例 |
|------|--------------------------|------|
| 端到端体验指标 | 是 | 首帧延迟、TTS 首包、事件流、WebRTC 播放、音画同步。 |
| 模型推理基线 | 否，来自所选 backend | OmniRT FlashTalk、Wav2Lip、QuickTalk 本地 adapter 的渲染吞吐。 |

内容先沿用 main 分支 `docs/zh/benchmark` 中的 benchmark 口径，后续有新的测试结果时再继续补充。

## 指标定义

| 指标 | 含义 | 归属 |
|------|------|------|
| `session_create_ms` | 创建会话到 API 返回的耗时。 | OpenTalking |
| `asr_partial_latency_ms` | 用户说话到首个 partial transcript 的延迟。 | OpenTalking + STT provider |
| `llm_first_token_ms` | 文本请求到首个 LLM token 的延迟。 | OpenTalking + LLM endpoint |
| `tts_first_pcm_ms` | 句子提交到首段 PCM/音频字节返回的延迟。 | OpenTalking + TTS provider |
| `avatar_first_frame_ms` | 音频提交到首帧 avatar 视频可用的延迟。 | OpenTalking + synthesis backend |
| `render_fps` | 合成 backend 的视频帧生成吞吐。 | synthesis backend |
| `webrtc_first_frame_ms` | 浏览器收到首个可播放视频帧的时间。 | OpenTalking + WebRTC |
| `av_drift_ms` | 音频与视频播放时间线的偏移。 | OpenTalking |
| `queue_depth` | Worker 或外部模型服务队列深度。 | OpenTalking / backend |
| `steady_chunk_ms` | 稳态 chunk 推理耗时。 | synthesis backend |

### 口径约束

- 首响类指标必须说明起点和终点，例如“用户结束说话到浏览器首帧”或“API 收到文本到 TTS 首包”。
- `render_fps` 只描述合成 backend，不等同于用户体感端到端 FPS。
- 多卡、NPU、远端模型服务需要额外记录网络拓扑和队列状态。

## 已测试组合

| 路径 | 硬件 / 状态 | 数据 | 说明 |
|------|-------------|------|------|
| Wav2Lip quickstart | NVIDIA 3090 路径 | `singer` 示例约 `28` 帧 / `0.83-0.85s`，约 `33 FPS` | 来自 README 的 quickstart 配置记录；用于轻量模型体验参考。 |
| QuickTalk local adapter | RTX 3090 | 720x900 / 25fps，约 `35 FPS`，显存约 `3.8 GiB` | 来自 README 的消费级显卡参考；用于 QuickTalk 本地 adapter 体验参考。 |
| FlashTalk via OmniRT | Ascend 910B2 x8，热态 full-audio | `937` 帧 / `37.377s`，约 `25 FPS` | 外部 OmniRT/模型服务推理基线，不代表 OpenTalking 本仓直接推理。 |
| FlashTalk steady chunk | Ascend 910B2 x8，热态 chunk | 29-frame chunk 约 `30 FPS` 等效 | 外部推理稳态数据，应与端到端首响分开记录。 |

## FPS

FPS 需要区分两种口径：

- `render_fps`：模型或 synthesis backend 生成帧的吞吐。
- 播放 FPS：浏览器或 WebRTC 实际播放帧率。

模型推理 FPS 高，不一定等于端到端体验好。真实体验还会受 TTS、队列、网络、WebRTC 和浏览器解码影响。

## 首帧时间

首帧时间建议拆成几个阶段记录：

- `session_create_ms`：会话创建耗时。
- `tts_first_pcm_ms`：TTS 首段音频返回耗时。
- `avatar_first_frame_ms`：音频进入模型后首帧可用耗时。
- `webrtc_first_frame_ms`：浏览器收到首个可播放视频帧耗时。

如果只记录一个“首帧时间”，后续很难判断瓶颈在 TTS、模型、队列还是播放链路。

## 启动时间

启动时间需要标注冷启动或热态：

- 冷启动：包含进程启动、模型加载、权重加载、Avatar 预处理和缓存构建。
- 热态：模型和缓存已经准备好，只测单次会话或单次 chunk。
- steady chunk：忽略首轮初始化，只测连续生成时的稳定吞吐。

QuickTalk 和 Wav2Lip 的首次 Avatar 初始化可能较慢，后续命中缓存会明显变快。

## 端到端延迟

端到端延迟建议从用户输入到浏览器可见输出来记录。不同输入形态有不同起点：

- 文本输入：用户提交文本。
- 语音输入：用户结束说话或 STT 产生稳定文本。
- 离线音频：音频文件提交到 API。

建议同时记录 TTS、模型和 WebRTC 阶段，否则只看总耗时无法定位问题。

## 资源占用

记录资源占用时建议包含：

- GPU / NPU 型号、数量和驱动版本。
- 显存峰值和稳定显存。
- CPU 核数和线程限制。
- 内存峰值。
- 模型权重版本。
- 是否启用量化、缓存和预热。

多模型部署时，还需要记录每个模型服务绑定的设备。

## 测试方法

### QuickTalk 本地 adapter

仓库提供 `apps/cli/quicktalk_bench.py`，用于直接测 QuickTalk 本地 adapter 的加载、首帧、渲染和 mux 时间。

```bash title="终端"
source .venv/bin/activate
python apps/cli/quicktalk_bench.py \
  --asset-root /path/to/quicktalk/assets \
  --template-video /path/to/template.mp4 \
  --audio /path/to/input.wav \
  --output outputs/benchmarks/quicktalk-output.mp4 \
  --device cuda:0
```

输出 JSON 包含：

- `init_seconds`
- `audio_feature_seconds`
- `first_frame_seconds`
- `render_seconds`
- `render_fps`
- `mux_seconds`

### OpenTalking 端到端链路

端到端测试应先固定模型、TTS provider 和输入音频，再记录浏览器、API 与 Worker 日志。

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/models | jq
```

建议记录：

- OpenTalking commit、配置文件、`.env` 中非密钥配置。
- 硬件与驱动版本。
- 选中的 `avatar_id`、`model`、`backend`。
- 输入音频时长、采样率和文本内容。
- 首 token、TTS 首包、avatar 首帧、浏览器首帧和音画同步结果。

### 外部模型服务

OmniRT、FlashHead direct WebSocket 或其它模型服务的推理数据应使用对应服务的 benchmark 工具生成。OpenTalking 文档只引用结果，并记录 OpenTalking 侧的调用、队列和播放表现。

## 结果模板

```markdown
### <模型> / <backend> / <硬件> / <日期>

- OpenTalking commit:
- backend commit 或服务版本:
- 硬件:
- 模型与权重:
- avatar:
- 输入音频:
- 冷启动或热态:
- `session_create_ms`:
- `llm_first_token_ms`:
- `tts_first_pcm_ms`:
- `avatar_first_frame_ms`:
- `webrtc_first_frame_ms`:
- `render_fps`:
- `av_drift_ms`:
- 备注:
```
