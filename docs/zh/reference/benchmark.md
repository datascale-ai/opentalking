# Benchmark

Benchmark 页面用于说明 OpenTalking 如何记录端到端体验指标，以及如何引用外部模型服务的推理基线。OpenTalking 是编排层，因此这里区分两类数据：

| 类型 | OpenTalking 是否直接负责 | 示例 |
|------|--------------------------|------|
| 端到端体验指标 | 是 | 首帧延迟、TTS 首包、事件流、WebRTC 播放、音画同步。 |
| 模型推理基线 | 否，来自所选 backend | OmniRT FlashTalk、Wav2Lip、QuickTalk 本地 adapter 的渲染吞吐。 |

内容先沿用 main 分支 `docs/zh/benchmark` 中的 benchmark 口径，后续有新的测试结果时再继续补充。

## 实测结果参考

下面是已记录的端到端或 backend 实测结果。阅读时优先看 `硬件`、`稳态FPS`、`首轮总延迟/ms` 和显存列；`稳态FPS` 是更接近模型持续生成能力的参考，不等同于完整用户体感延迟。

| 测试日期 | 模型 | 硬件 | 稳态FPS | 输出FPS | 输出分辨率 | 首轮总延迟/ms | TTFA/ms | TTFV/ms | 推理峰值显存/GB | 冷启动时间/s | 预热时间/s | backend | OS | 驱动环境 | commit (opentalking + omnirt) | 输入类型 | chunk size | idle显存/GB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026/5/20 | wav2lip | RTX 3090 | 37.269 | 30 | 498×832 | 3002.526 | 1374.507 | 1625.962 | 7.928 | 4.096 | 12.043 | omnirt | Linux x86_64 glibc2.31 | driver 570.133.07 | a3047eab + 64c92ed1 | audio+image | 933ms | 7.928 |
| 2026/5/20 | quicktalk | RTX 3090 | 29.23 | 25 | 540×900 | 3356.019 | 1551.773 | 1800.524 | 1.662 | 5.702 | 17.856 | omnirt | Linux x86_64 glibc2.31 | driver 570.133.07 | a3047eab + 64c92ed1 | audio+image | 1120ms | 1.662 |
| 2026/5/20 | musetalk | RTX 3090 | 28.868 | 25 | 512×512 | 3235.518 | 1464.464 | 1769.484 | 5.078 | 21.927 | 10.233 | omnirt | Linux x86_64 glibc2.31 | driver 570.133.07 | a3047eab + 64c92ed1 | audio+image | 1000ms | 5.078 |
| 2026/5/22 | wav2lip | RTX 4090 | 31.542 | 30 | 498×832 | 3689.764 | 1730.871 | 1955.629 | 8.133 | 4.23 | 27.321 | omnirt | Linux x86_64 glibc2.39 | driver 570.211.01 | f16f7868 + 9a35e675 | audio+image | 933ms | 8.133 |
| 2026/5/22 | quicktalk | RTX 4090 | 46.921 | 25 | 540×900 | 2561.146 | 1493.164 | 1064.825 | 1.838 | 4.319 | 15.871 | omnirt | Linux x86_64 glibc2.39 | driver 570.211.01 | f16f7868 + 9a35e675 | audio+image | 1120ms | 1.838 |
| 2026/5/22 | musetalk | RTX 4090 | 24.767 | 25 | 512×512 | 3605.564 | 1506.636 | 2095.522 | 5.203 | 18.309 | 13.866 | omnirt | Linux x86_64 glibc2.39 | driver 570.211.01 | f16f7868 + 9a35e675 | audio+image | 1000ms | 5.203 |
| 2026/5/22 | wav2lip | NPU 910B2 | 23.945 | 30 | 498×832 | 4019.564 | 1401.98 | 2615.322 | 9.113 | 9.478 | 35.931 | omnirt | Linux aarch64 glibc2.35 | cann driver | f3532c19 + 5f24f56f | audio+image | 933ms | 9.113 |
| 2026/5/22 | quicktalk | NPU 910B2 | 29.66 | 25 | 540×900 | 3212.053 | 1427.894 | 1782.861 | 2.473 | 9.471 | 39.142 | omnirt | Linux aarch64 glibc2.35 | cann driver | f3532c19 + 5f24f56f | audio+image | 1120ms | 2.473 |
| 2026/5/22 | musetalk | NPU 910B2 | 12.276 | 25 | 512×512 | 5781.453 | 1566.821 | 4211.721 | 8.754 | 27.177 | 65.282 | omnirt | Linux aarch64 glibc2.35 | cann driver | f3532c19 + 5f24f56f | audio+image | 1000ms | 8.754 |
| 2026/5/27 | quicktalk | RTX 3050 Laptop | 19.06 | 25 | 540×900 | 4109 | 1661 | 2833 | 1.41 | 5.98 | 20.77 | omnirt | WSL2 glibc2.35 | driver 581.57 | 3c893c52 + 5f24f56f | audio+image | 1120ms | 1.41 |
| 2026/5/27 | quicktalk | RTX 3050 Laptop | 20.695 | 25 | 306×512 | 4243.26 | 1580.28 | 2661 | 1.396 | 6.282 | 20.78 | omnirt | WSL2 glibc2.35 | driver 581.57 | 3c893c52 + 5f24f56f | audio+image | 1120ms | 1.385 |

RTX 3050 Laptop 可以跑通 QuickTalk 链路，但实时性能有限，适合部署验证和功能演示；如果目标是稳定 25fps+，建议使用 RTX 3060 / 4060 或更高规格 GPU。RTX 3090 / 4090 更适合消费级单机验证，NPU 910B2 和多卡 GPU 更适合远端推理或生产隔离路线。

## 运行完整 E2E Benchmark

完整链路 benchmark 直接使用：

```bash
scripts/run_opentalking_e2e_benchmark.sh
```

这个脚本会按照 benchmark 配置读取输入素材、启动相关服务并采集结果。

进入 OpenTalking：

```bash
cd $DIGITAL_HUMAN_HOME/opentalking
source .venv/bin/activate
```

准备脚本权限：

```bash
chmod +x scripts/run_opentalking_e2e_benchmark.sh
chmod +x scripts/start_unified.sh
chmod +x scripts/quickstart/start_omnirt_quicktalk.sh
```

确认 benchmark 默认输入存在：

```bash
ls -lh configs/benchmark/input/reference.png
ls -lh configs/benchmark/input/ttsmaker-file.mp3
```

如果要替换测试头像或音频，直接替换上面两个文件，或修改 `configs/benchmark/opentalking-e2e.yaml` 中的输入路径即可。一般部署验证时，使用仓库自带 benchmark 输入即可。

设置低显存环境变量：

```bash
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128
export OPENTALKING_BENCHMARK_PYTHON="$PWD/.venv/bin/python"

export OPENTALKING_QUICKTALK_HUBERT_DEVICE=cpu
export OPENTALKING_QUICKTALK_RESOLUTION=160
export OPENTALKING_PREWARM_AVATARS=0

export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_DEVICE=cuda:0
export OMNIRT_QUICKTALK_HUBERT_DEVICE=cpu
export OMNIRT_QUICKTALK_BATCH_SIZE=1
export OMNIRT_QUICKTALK_WORKER_CACHE_MAX=1
```

运行 benchmark：

```bash
bash scripts/run_opentalking_e2e_benchmark.sh \
  --tester xxx \
  --model quicktalk \
  --backend omnirt \
  --gpu-index 0 \
  --timeout 300
```

查找结果：

```bash
find $DIGITAL_HUMAN_HOME/opentalking -name "result.json" -o -name "result.csv" -o -name "report.md" -o -name "*.tar.gz"
```

### 说明

`run_opentalking_e2e_benchmark.sh` 是完整链路入口。它比单独跑模型 benchmark 更适合最终部署验证，因为它覆盖了 OpenTalking、OmniRT、QuickTalk runtime、输入处理、服务启动、请求链路和结果统计。

---

## WSL2 显存统计修复

WSL2 下，下面这个命令可能拿不到进程级显存：

```bash
nvidia-smi --query-compute-apps=pid,used_memory
```

因此 benchmark 中可能出现：

```text
idle 显存: 0.0
推理峰值显存: 0.0
```

推荐口径：当 PID 级查询为空时，fallback 到整卡显存：

```bash
nvidia-smi --id=0 --query-gpu=memory.used --format=csv,noheader,nounits
```

计算方式：

```text
推理峰值显存 = max(current memory.used - baseline memory.used)
```

说明：

- 这不是单进程显存；
- 这是 benchmark 运行期间整卡显存相对 baseline 的增量；
- benchmark 期间不要同时运行其他 CUDA 程序。

---

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

---
