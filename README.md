<h1 align="center">OpenTalking</h1>

<p align="center">
  <b>面向实时对话的开源数字人产线：LLM、TTS、WebRTC、角色音色与外部 OmniRT 模型服务</b>
</p>

<p align="center">
  <a href="./README.en.md">English</a> ·
  <a href="https://github.com/datascale-ai/opentalking">GitHub</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg" alt="Python">
  <img src="https://img.shields.io/badge/React-18-61dafb.svg" alt="React">
  <img src="https://img.shields.io/badge/FastAPI-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/WebRTC-realtime-orange.svg" alt="WebRTC">
</p>

<p align="center">
  <a href="#当前能力">当前能力</a> ·
  <a href="#交流与联系">交流与联系</a> ·
  <a href="#视频展示">视频展示</a> ·
  <a href="#系统架构">系统架构</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="#致谢">致谢</a>
</p>

---

## 项目简介

OpenTalking 是一个开源实时数字人框架，目标是把 **数字人对话产品** 需要的链路串起来：前端交互、会话状态、LLM 回复、TTS/音色选择、打断控制、字幕事件、WebRTC 音视频播放，以及外部模型服务调用。

OpenTalking 关注的是 **产线编排层**，支持调用外部 API 和本地部署模型。默认入口优先让新用户先跑通完整链路，再按需要升级模型能力：

- **快速体验**：`mock / 无驱动模式`，不需要独立模型服务，适合第一次验证 API、TTS、WebRTC 和前端。
- **轻量适配验证**：通过 [OmniRT](https://github.com/datascale-ai/omnirt) 启动 `wav2lip`，用于验证 Avatar 资产格式、模型适配器和端到端编排。
- **QuickTalk 实时路径**：`quicktalk` 本地适配器，支持流式 LLM → 句级 TTS → 实时口型渲染，并可通过 Worker 缓存降低首轮等待。
- **高质量部署**：通过 OmniRT 接入 `flashtalk` 等高质量模型，面向 GPU/NPU 私有化推理服务。

## 当前能力

- **实时数字人对话**：LLM 回复、流式 TTS、字幕事件、状态事件和 WebRTC 播放在一条链路中完成。
- **FlashTalk 兼容路径**：支持本地或远端 FlashTalk 风格推理服务，作为高质量数字人渲染后端。
- **轻量 Demo 路径**：无需先下载完整 FlashTalk 权重，也可以跑通 API、TTS、WebRTC 和前端体验。
- **基础打断能力**：当前说话轮次已有打断基础，后续会升级为全链路取消。
- **OpenAI 兼容 LLM**：支持 DashScope、Ollama、vLLM、DeepSeek 等 OpenAI-compatible endpoint。
- **多部署形态**：支持单进程 demo、API/Worker 分布式模式和 Docker Compose。
- **QuickTalk 适配器**：内置 `quicktalk` 模型注册、Avatar 校验、实时渲染队列、音画同步和 benchmark CLI。

## 交流与联系

欢迎加入 QQ 交流群，讨论实时数字人、FlashTalk、OmniRT、模型部署和产品场景。

<p align="center">
  <img src="docs/assets/images/qq_group_qrcode.png" alt="AI 数字人交流群二维码" width="280">
</p>

<p align="center">
  <b>AI 数字人交流群</b> · 群号：<code>1103327938</code>
</p>

## 视频展示

以下是 OpenTalking 典型场景演示视频，用来展示实时数字人产线在不同内容形态下的表现。横屏示例单独占一行，其余为竖屏，避免同一行里行高被横屏拉高导致竖屏看起来像被裁切。

<table>
  <tr>
    <td align="center" colspan="3">
      <b>实时手机录制</b><br/>
      <video src="https://github.com/user-attachments/assets/a3abce76-12c0-4b8b-844f-bbc5c3227dc7" controls width="100%"></video><br/>
    </td>
  </tr>
  <tr>
    <td align="center" valign="top" width="33%">
      <b>动漫脱口秀</b><br/>
      <video src="https://github.com/user-attachments/assets/b3743604-7f50-40d1-9248-f2df80ea7308" controls width="100%"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>电商带货</b><br/>
      <video src="https://github.com/user-attachments/assets/826c777b-a9d2-49be-a1a0-b295c8a4b498" controls width="100%"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>新闻女主播</b><br/>
      <video src="https://github.com/user-attachments/assets/34a282da-84cb-4134-bc4b-644356ac4f6f" controls width="100%"></video><br/>
    </td>
  </tr>
  <tr>
    <td align="center" valign="top" colspan="3">
      <table>
        <tr>
          <td align="center" valign="top" width="50%">
            <b>创意演唱 / 模仿秀</b><br/>
            <video src="https://github.com/user-attachments/assets/98e813c2-f170-4cc8-b934-a77a72061d2e" controls width="100%"></video><br/>
          </td>
          <td align="center" valign="top" width="50%">
            <b>陪伴类角色</b><br/>
            <video src="https://github.com/user-attachments/assets/44bbf1d9-75b1-4b0a-9704-c7f81c39446e" controls width="100%"></video><br/>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>

## 系统架构

![OpenTalking Architecture](docs/assets/images/opentalking_architecture.png)

## 项目结构

```text
opentalking/
├── opentalking/                  # 编排层 Python 包（flat layout，根目录直接 import）
│   ├── core/                     # 接口协议、类型、配置、registry
│   ├── providers/                # 能力适配器（按"能力域 / 提供方"两级）
│   │   ├── stt/dashscope/        # 语音识别
│   │   ├── tts/{edge,dashscope_qwen,cosyvoice_ws,...}/   # 语音合成 + 复刻
│   │   ├── llm/openai_compatible/                        # 大语言模型
│   │   ├── rtc/aiortc/                                   # WebRTC 推流
│   │   └── synthesis/{flashtalk,flashhead,omnirt,mock}/  # 数字人合成（thin client）
│   ├── avatar/                   # 数字人形象资产管理
│   ├── voice/                    # 音色资产管理
│   ├── media/                    # 中性算子工具
│   ├── pipeline/{session,speak,recording}/   # 业务编排
│   └── runtime/                  # 进程胶水（task_consumer / bus / timing）
├── apps/
│   ├── api/                      # FastAPI 服务
│   ├── unified/                  # 单进程模式（开发友好）
│   ├── web/                      # React 前端
│   └── cli/                      # download_models / doctor / ...
├── configs/                      # YAML 配置（profiles / inference / synthesis）
├── docker/ + docker-compose.yml  # 容器化部署
├── scripts/                      # 辅助脚本（run_omnirt.sh / prepare-avatar.sh）
├── tests/                        # 单元 / 集成测试
└── docs/                         # 文档
```

## 快速开始

OpenTalking 是主入口，负责 Web、API、LLM、TTS、WebRTC、Avatar 资产和模型选择；[OmniRT](https://github.com/datascale-ai/omnirt) 是独立的推理服务，负责 Wav2Lip、FlashTalk 等真实数字人模型。两者可以跑在同一台机器，也可以分开部署。

OpenTalking 只需要一个统一推理入口：

```env
OMNIRT_ENDPOINT=http://<omnirt-host>:9000
```

当前端选择 `wav2lip` 或 `flashtalk` 时，OpenTalking 会自动连接：

```text
ws://<omnirt-host>:9000/v1/audio2video/{model}
```

前端模型列表保持不变。`mock / 无驱动模式` 是本地自测模式，不需要 OmniRT；真实模型卡片会根据 OmniRT 状态显示 **已连接** 或 **未连接**。

### 0. 环境要求

OpenTalking:

- Python 3.10+
- uv
- Node.js 18+
- FFmpeg

OmniRT 真实模型服务:

- **GPU / CUDA**：NVIDIA driver，CUDA-capable PyTorch 环境。
- **NPU / Ascend 910B**：Ascend driver，CANN toolkit，`torch-npu` 环境。

真实模型建议：

| 模型 | 推荐用途 | 显存 / 内存建议 | 已测试硬件 | 实测吞吐 | 说明 |
| --- | --- | ---: | --- | --- | --- |
| `wav2lip` | 最快跑通真实口型同步 | 预留 `>= 8 GB` GPU/NPU memory | CUDA GPU、Ascend 910B 路径已 smoke test | `singer` 在 CUDA quickstart 配置下约 `28` 帧 / `0.83-0.85s`，约 `33 FPS`，可覆盖 30 fps 播放 | 推荐第一次真实模型验证使用，权重小、启动和排错快 |
| `flashtalk` | 更高质量数字人生成 | 推荐多卡 Ascend 910B 或显存优化 CUDA 配置 | Ascend 910B2 x8 resident worker benchmark 已跑通；CUDA FlashTalk 属高级路径 | Ascend 910B2 x8：hot full-audio `937` 帧 / `37.377s`，约 `25 FPS`；稳态 29-frame chunk 约 `30 FPS` 等效 | 权重大、部署重；适合工业级或私有化质量优先场景 |

如果只是想最快看到结果，先跑 `mock`，再选一个真实驱动模型。推荐先下载并启动 `wav2lip`；需要更高质量时再部署 `flashtalk`。

包下载慢时可以先设置镜像：

```bash
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# 或：
# export UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
```

设置一个工作目录，后续所有 terminal 保持一致：

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human
# 或你自己的路径，例如：
# export DIGITAL_HUMAN_HOME=/data/digital_human
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
```

推荐目录结构：

```text
$DIGITAL_HUMAN_HOME/
  opentalking/
  omnirt/
  models/
    wav2lip/
      wav2lip384.pth
      s3fd.pth
    SoulX-FlashTalk-14B/
    chinese-wav2vec2-base/
```

每个新 terminal 都需要重新 export 这两个变量。安装 OpenTalking 后，也可以把它们写入本仓的 quickstart 本地配置文件，避免每个 terminal 重复输入。

### 1. 安装 OpenTalking

```bash
mkdir -p "$DIGITAL_HUMAN_HOME"
cd "$DIGITAL_HUMAN_HOME"

git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

uv sync
uv pip install -e ".[dev]"
source .venv/bin/activate

cp .env.example .env
```

可选：把常用路径写入 quickstart 本地配置文件：

```bash
cp scripts/quickstart/env.example scripts/quickstart/env
```

然后编辑 `scripts/quickstart/env`。这个文件是本地私有配置，不会提交到 git。

编辑 `.env`，至少配置 LLM / STT / TTS：

```env
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-key
OPENTALKING_LLM_MODEL=qwen-flash

DASHSCOPE_API_KEY=sk-your-key

OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

`edge` TTS 不需要 key。`DASHSCOPE_API_KEY` 只在使用实时 STT 时需要。

### 2. 先跑 Mock 自测

这一步用于先验证前端、API、LLM、TTS、STT、WebRTC 和浏览器链路，不需要下载模型权重，也不需要启动 OmniRT。

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_mock.sh
```

浏览器打开网页，如果是服务器的话，将localhost换成服务器ip：

```text
http://localhost:5173
```

选择 `无驱动模式`，任选一个 avatar，点击 `开始对话`。这个模式不会连接 OmniRT 或任何真实驱动模型。如果可以听到语音并看到会话页，说明 OpenTalking 主链路已经跑通。

测试结束后停止本地服务：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/stop_all.sh
```

### 3. 安装 OmniRT

在有 GPU 或 NPU 的机器上执行：

```bash
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt

uv sync --extra server
source .venv/bin/activate
uv pip install -U "huggingface_hub[cli]"
```

如果部署在 Ascend 910B，安装或启动 NPU 服务前先 source CANN：

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
```

如果你的 CANN 路径不同，把上面的路径替换成实际的 `set_env.sh`。

### 4. 下载模型权重

部分模型需要先在 Hugging Face 页面接受 license 或申请权限。如果下载返回 `401`、`403` 或 `Repository not found`，先打开模型页面确认权限，再执行 `hf auth login`。

只下载你要跑的模型即可：

- 想最快跑通真实数字人，选 **Wav2Lip**。
- 想要更高质量，且硬件资源足够，选 **FlashTalk**。
- 想测试多模型切换时再两个都下载。

Hugging Face 下载慢或容易中断时可配置镜像和传输加速：

```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_ENABLE_HF_TRANSFER=1
uv pip install -U hf_transfer
```

如果 gated/private 模型没有被镜像，取消镜像后重试：

```bash
unset HF_ENDPOINT
```

登录并创建模型目录：

```bash
cd "$DIGITAL_HUMAN_HOME/omnirt"
source .venv/bin/activate

hf auth login

export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
```

下载 Wav2Lip：

```bash
hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"

hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

检查文件：

```bash
test -f "$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
test -f "$OMNIRT_MODEL_ROOT/wav2lip/s3fd.pth"
```

**以下为可选项，wav2lip和flashtalk二选一即可**

下载 FlashTalk：

```bash
hf download Soul-AILab/SoulX-FlashTalk-14B \
  --local-dir "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B"

hf download TencentGameMate/chinese-wav2vec2-base \
  --local-dir "$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base"
```

SoulX-FlashTalk 的推理代码不是模型权重。推荐的 Ascend 910B 路径会由 OmniRT 的 runtime install 流程准备代码、打补丁并记录 runtime 状态；只有使用自定义 fork 或 CUDA 手动路径时，才需要指定自己的 SoulX checkout。

模型页面：

- Wav2Lip 384: https://huggingface.co/Pypa/wav2lip384
- Wav2Lip S3FD: https://huggingface.co/rippertnt/wav2lip
- SoulX FlashTalk code: https://github.com/Soul-AILab/SoulX-FlashTalk
- SoulX FlashTalk 14B: https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B
- Chinese wav2vec2: https://huggingface.co/TencentGameMate/chinese-wav2vec2-base

### 5. 启动 Wav2Lip OmniRT

CUDA GPU:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

Ascend 910B NPU:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device npu
```

验证：

```bash
curl http://127.0.0.1:9000/v1/audio2video/models
```

`wav2lip` 应该返回 `connected: true`。

这个 helper 默认设置：

- `OMNIRT_WAV2LIP_CPU_THREADS=4`
- `OMNIRT_WAV2LIP_PRELOAD=1`
- `OMNIRT_WAV2LIP_MAX_LONG_EDGE=832`
- CUDA batch size 默认 `16`
- Ascend NPU batch size 默认 `8`

环境已经装好后，重复启动可以加 `--skip-install`。
如果你的 OmniRT checkout 还没有定义 `wav2lip-cuda` extra，helper 会自动回退到 `model_backends/wav2lip/requirements-wav2lip.txt` 安装；也建议先更新 OmniRT 到最新 `main`。

### 6. 启动 FlashTalk OmniRT（可选）

FlashTalk 比 Wav2Lip 更重。建议先跑通 Wav2Lip，再启动 FlashTalk。

CUDA GPU：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
```

Ascend 910B NPU：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu --nproc 8
```

验证：

```bash
curl http://127.0.0.1:9000/v1/audio2video/models
```

`flashtalk` 应该返回 `connected: true`。

### 7. 连接 OpenTalking 到 OmniRT

同机部署：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/configure_omnirt_endpoint.sh http://127.0.0.1:9000
```

远端 OmniRT：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/configure_omnirt_endpoint.sh http://<gpu-or-npu-server-ip>:9000
```

### 8. 启动 OpenTalking 真实模型模式

保持第 5 或第 6 步启动的 OmniRT 服务运行，然后启动 OpenTalking API 和前端：

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

如果 OmniRT 在远端机器：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_all.sh --omnirt http://<gpu-or-npu-server-ip>:9000
```

检查 OpenTalking 是否能看到 OmniRT：

```bash
curl http://127.0.0.1:8000/models
```

浏览器打开：

```text
http://localhost:5173
```

选择 `wav2lip` 或 `flashtalk`。真实模型卡片应显示 **已连接**；`mock / 无驱动模式` 会显示 **无需连接**。

查看或停止 helper 管理的服务：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/status.sh
bash scripts/quickstart/stop_all.sh
```

### 故障排查

模型显示 **未连接**：

```bash
curl http://<omnirt-host>:9000/v1/audio2video/models
grep OMNIRT_ENDPOINT "$DIGITAL_HUMAN_HOME/opentalking/.env"
```

如果 OmniRT 在 `9000` 端口已连接，但 OpenTalking 的 `/models` 仍显示未连接，更新 `.env` 后重启 OpenTalking，或重新运行 `start_all.sh --omnirt ...`。

Wav2Lip 报 `ref_frame_dir requires configured allowed frame roots` 时，需要允许 OpenTalking avatar 目录：

```bash
export OMNIRT_ALLOWED_FRAME_ROOTS="$DIGITAL_HUMAN_HOME/opentalking/examples/avatars"
```

然后重启 OmniRT。

Wav2Lip 报缺少 `s3fd.pth` 时，确认文件在：

```text
$OMNIRT_WAV2LIP_MODELS_DIR/wav2lip/s3fd.pth
$OMNIRT_WAV2LIP_MODELS_DIR/s3fd.pth
```

重新下载：

```bash
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

日志出现 `avcodec_open2(libx264)` 时，通常是 H.264 编码遇到奇数宽高。新版本 OmniRT 会把 Wav2Lip 缩放后的宽高对齐到偶数；如果你使用旧代码，可以先设置：

```bash
export OMNIRT_WAV2LIP_MAX_LONG_EDGE=832
```

再重启 OmniRT 和浏览器会话。


## Roadmap

- [x] **实时数字人基础体验**
  Web 控制台、LLM 对话、TTS、字幕事件、WebRTC 音视频播放。

- [ ] **更自然的实时对话（进行中）**
  支持打断、会话状态、低延迟响应、音画同步和异常恢复。

- [x] **OmniRT 模型服务接入**
  通过 OmniRT 统一调用 FlashTalk、轻量 talking-head、ASR、语音合成和音色服务。

- [x] **消费级显卡可用**
  面向 RTX 3090 / 4090 提供轻量模型、单卡实时配置和端到端 benchmark。

- [ ] **高质量私有化部署（进行中）**
  面向企业私有化场景，支持外部 OmniRT 推理服务、容量调度、健康检查和生产监控；昇腾 910B 等企业级 GPU/NPU 路线已在构建中。

- [x] **自定义角色和音色**
  支持角色配置、内置音色选择、上传参考音频、自然语言描述音色，并通过 OmniRT 生成语音。

- [ ] **Agent 与记忆能力**
  对接 OpenClaw 或外部 Agent，复用其 memory、工具调用和知识库能力。

- [ ] **生产级平台能力**
  多会话调度、观测指标、安全合规、授权音色、合成内容标识。

## 文档

- [快速开始](docs/quickstart.md)
- [FlashTalk + OmniRT 部署](docs/flashtalk-omnirt.md)
- [架构说明](docs/architecture.md)
- [配置说明](docs/configuration.md)
- [部署文档](docs/deployment.md)（Docker Compose、分布式部署）
- [硬件指南](docs/hardware.md)
- [模型适配](docs/model-adapter.md)
- [贡献指南](CONTRIBUTING.md)（开发环境、CLI 工具、ruff / mypy / pytest）

## 致谢

OpenTalking 参考并受益于实时数字人生态中的优秀项目：

- [SoulX-FlashTalk](https://github.com/Soul-AILab/SoulX-FlashTalk) 和 [SoulX-FlashTalk-14B](https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B)
- [LiveTalking](https://github.com/lipku/LiveTalking)
- [OmniRT](https://github.com/datascale-ai/omnirt)
- [Edge TTS](https://github.com/rany2/edge-tts)
- [aiortc](https://github.com/aiortc/aiortc)
- [Wan Video](https://github.com/Wan-Video)

## License

[Apache License 2.0](LICENSE)
