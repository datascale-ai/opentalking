<h1 align="center">OpenTalking</h1>

<p align="center">
  <b>面向实时对话的开源数字人产线：LLM、TTS、WebRTC、角色音色与可插拔模型后端</b>
</p>

<p align="center">
  <a href="./README.en.md">English</a> ·
  <a href="https://datascale-ai.github.io/opentalking/">📖 文档站</a> ·
  <a href="https://github.com/datascale-ai/opentalking">GitHub</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg" alt="Python">
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
  <a href="#文档">文档</a> ·
  <a href="#致谢">致谢</a>
</p>

---

## 项目简介

OpenTalking 是一个开源实时数字人框架，目标是把 **数字人对话产品** 需要的链路串起来：前端交互、会话状态、LLM 回复、TTS/音色选择、打断控制、字幕事件、WebRTC 音视频播放，以及外部模型服务调用。

OpenTalking 关注的是 **产线编排层**，支持调用外部 API 和本地部署模型。默认入口优先让新用户先跑通完整链路，再按需要升级模型能力：

- **快速体验**：`mock / 无驱动模式`，不需要独立模型服务，适合第一次验证 API、TTS、WebRTC 和前端。
- **轻量适配验证**：`wav2lip` / `musetalk` 可按配置选择本地、单模型直连或 OmniRT 后端，用于验证 Avatar 资产格式、模型适配器和端到端编排。
- **高质量部署**：通过 OmniRT 接入 `flashtalk` 等高质量模型，面向 GPU/NPU 私有化推理服务。

- 在线文档固定地址：<https://datascale-ai.github.io/opentalking/>
- 英文文档入口：<https://datascale-ai.github.io/opentalking/en/>

## 当前能力

- **实时数字人对话**：LLM 回复、流式 TTS、字幕事件、状态事件和 WebRTC 播放在一条链路中完成。
- **FlashTalk 兼容路径**：支持本地或远端 FlashTalk 风格推理服务，作为高质量数字人渲染后端。
- **轻量 Demo 路径**：无需先下载完整 FlashTalk 权重，也可以跑通 API、TTS、WebRTC 和前端体验。
- **基础打断能力**：当前说话轮次已有打断基础，后续会升级为全链路取消。
- **OpenAI 兼容 LLM**：支持 DashScope、Ollama、vLLM、DeepSeek 等 OpenAI-compatible endpoint。
- **多部署形态**：支持单进程 demo、API/Worker 分布式模式和 Docker Compose。

## 交流与联系

欢迎加入 QQ 交流群，讨论实时数字人、FlashTalk、OmniRT、模型部署和产品场景。

<p align="center">
  <img src="docs/assets/images/qq_group_qrcode.png" alt="AI 数字人交流群二维码" width="280">
</p>

<p align="center">
  <b>AI 数字人交流群</b> · 群号：<code>1103327938</code>
</p>

## 数字人服务界面

OpenTalking 提供 Web 服务界面，用于管理数字人对话链路：可以选择或新建数字人物，配置音色、LLM、TTS、STT 和数字人驱动模型，查看模型连接状态，并在同一页面完成实时对话、字幕和音视频播放验证。

![OpenTalking WebUI](docs/assets/images/WebUI.png)

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

![OpenTalking 当前代码架构图](docs/assets/images/opentalking_architecture_zh.png)

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

OpenTalking 的 **编排层**（API / Worker / 前端）和 **数字人合成 backend**（`mock`、`local`、`direct_ws` 或 [OmniRT](https://github.com/datascale-ai/omnirt)）可以独立部署。先用 Mock 跑通完整链路，再按需求切到 Wav2Lip、MuseTalk 或 FlashTalk。

### 0. 安装编排层

```bash
git clone https://github.com/datascale-ai/opentalking.git && cd opentalking
uv sync --extra dev --python 3.11
source .venv/bin/activate
cp .env.example .env
```

OpenTalking 是主入口，负责 Web、API、LLM、TTS、WebRTC、Avatar 资产和模型选择；[OmniRT](https://github.com/datascale-ai/omnirt) 是独立的推理服务，负责 Wav2Lip、MuseTalk、FlashTalk 等真实数字人模型。两者可以跑在同一台机器，也可以分开部署。

按照接下来的步骤，可以快速部署属于你的数字人服务。

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

| 模型 | 推荐用途 | 资源建议 | 已验证硬件 |
| --- | --- | --- | --- |
| `wav2lip` | 快速口型同步 | 预留 `>= 8 GB` GPU / NPU memory | RTX 3090、Ascend 910B |
| `musetalk` | 轻量全帧 talking-head | 预留 `>= 12 GB` GPU memory | RTX 3090 |
| `flashtalk` | 高质量数字人生成 | 多卡 Ascend 910B | Ascend 910B2 x8 |

实测吞吐参考：

- `wav2lip`：`singer` 在 CUDA quickstart 配置下约 `28` 帧 / `0.83-0.85s`，约 `33 FPS`，可覆盖 30 fps 播放。
- `flashtalk`：Ascend 910B2 x8，hot full-audio `937` 帧 / `37.377s`，约 `25 FPS`；稳态 29-frame chunk 约 `30 FPS` 等效。

如果只是想最快看到结果，先跑 `无驱动模式`，再选一个真实驱动模型测试。真实模式推荐先使用 `wav2lip`；想验证全帧 talking-head 路径时使用 `musetalk`；需要更高质量时再部署 `flashtalk`。

uv 包下载慢时可以先设置国内镜像源：

```bash
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
# 或：
# export UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple
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
    musetalk/
      pytorch_model.bin
      musetalk.json
    sd-vae-ft-mse/
    whisper/
      tiny.pt
    dwpose/
      dw-ll_ucoco_384.pth
    face-parse-bisenet/
      79999_iter.pth
    SoulX-FlashTalk-14B/
    chinese-wav2vec2-base/
```

要求：Python 3.10+（推荐 3.11）、Node.js 18+、FFmpeg。若环境不便使用 `uv`，可用兼容安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

编辑 `.env`，至少配置 LLM / TTS；`edge` TTS 不需要 key：

```env
# LLM模型配置（百炼、DeepSeek、豆包等）
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-key
OPENTALKING_LLM_MODEL=qwen-flash

# 声音合成/声音复刻（若使用百炼后端）
DASHSCOPE_API_KEY=sk-your-key

# 其他声音合成选项
OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

运行 `opentalking-doctor` 可以检查本机依赖状态。
真实模型模式启动时通过 `--omnirt` 指定视频合成推理入口。网页前端选择 `wav2lip`、`musetalk` 或 `flashtalk` 时，OpenTalking 会自动连接对应模型。

> 注意：`mock / 无驱动模式` 是本地自测模式，不需要 OmniRT；真实模型卡片会根据 OmniRT 状态显示 **已连接** 或 **未连接**。`edge` TTS 不需要 key。`DASHSCOPE_API_KEY` 只在使用实时 STT 时需要。

### 路径 1：快速体验（推荐首次运行）

目标：不下载模型权重、不启动 OmniRT，先验证前端、API、LLM、TTS、STT、WebRTC 和浏览器链路。数字人画面使用内置 Mock 静态帧，LLM 回复、流式 TTS、字幕事件和 WebRTC 传输仍是真链路。

```bash
bash scripts/quickstart/start_mock.sh
```

默认前端地址是 `http://localhost:5173`。如果需要改端口：

```bash
bash scripts/quickstart/start_mock.sh --api-port 8010 --web-port 5180
```

停止 helper 管理的服务：

```bash
bash scripts/quickstart/stop_all.sh
```

### 路径 2：轻量模型验证

目标：验证 Avatar 资产、模型适配器和真实口型同步。轻量模型可走本地 adapter、单模型直连 WebSocket，或当前最稳妥的 OmniRT 兼容路径。

先在同级目录安装 OmniRT，并准备模型目录：

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

mkdir -p "$DIGITAL_HUMAN_HOME"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt
uv sync --extra server --python 3.11
source .venv/bin/activate
uv pip install -U "huggingface_hub[cli]"
```

#### 1. 下载模型权重

部分模型需要先在 Hugging Face 页面接受 license 或申请权限。如果下载返回 `401`、`403` 或 `Repository not found`，先打开模型页面确认权限，再执行 `hf auth login`。

只下载你要跑的模型即可：

- 想最快跑通真实数字人，选 **Wav2Lip**。
- 想测试全帧 talking-head，选 **MuseTalk**。
- 想要更高质量，且硬件资源足够，选 **FlashTalk**。
- 想测试多模型切换时再按需多下载。

Hugging Face 下载慢或容易中断时可配置镜像和传输加速：

```bash
export HF_ENDPOINT=https://hf-mirror.com
hf auth login
```

下载 Wav2Lip：

```bash
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

检查 Wav2Lip 文件：

```bash
test -f "$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
test -f "$OMNIRT_MODEL_ROOT/wav2lip/s3fd.pth"
```

下载 MuseTalk：

MuseTalk 的运行时代码由 OmniRT 的 `runtime install musetalk` 自动拉取；OpenTalking 侧不需要额外指定 repo。你只需要把权重放到 `$OMNIRT_MODEL_ROOT` 下，布局满足 MuseTalk v1.5 的要求：

```text
$OMNIRT_MODEL_ROOT/
  musetalk/
    pytorch_model.bin
    musetalk.json
  sd-vae-ft-mse/
    config.json
    diffusion_pytorch_model.bin
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

检查 MuseTalk 文件：

```bash
test -f "$OMNIRT_MODEL_ROOT/musetalk/pytorch_model.bin"
test -f "$OMNIRT_MODEL_ROOT/musetalk/musetalk.json"
test -f "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse/config.json"
test -f "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse/diffusion_pytorch_model.bin"
test -f "$OMNIRT_MODEL_ROOT/whisper/tiny.pt"
test -f "$OMNIRT_MODEL_ROOT/dwpose/dw-ll_ucoco_384.pth"
test -f "$OMNIRT_MODEL_ROOT/face-parse-bisenet/79999_iter.pth"
```

说明：

- 官方 MuseTalk README / `download_weights.sh` 里还会提到 `syncnet/latentsync_syncnet.pt`。
- 当前 OpenTalking + OmniRT 的 MuseTalk 路径只使用 **实时推理** 所需的权重：UNet、VAE、Whisper、DWPose、face-parse。
- `syncnet` 在官方仓里主要用于 **训练 / 评估 / lip-sync 打分**，不是当前 `musetalk_ws_server.py` 在线推理链的必需项，因此这里不要求下载。
- 如果后续要继续训练 MuseTalk、复现实验脚本，或引入基于 SyncNet 的离线评分/筛选流程，再额外补 `syncnet` 权重即可。
- 其中 `whisper/tiny.pt` 必须是 OpenAI `openai-whisper` 官方 checkpoint，不要用 Hugging Face 的 `pytorch_model.bin` 改名替代。

更完整的权重说明、目录要求与排错见：

- `omnirt/model_backends/musetalk/README.md`
- `omnirt/docs/user_guide/serving/musetalk_ws.md`

下载 FlashTalk（可选）：

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
- MuseTalk code: https://github.com/TMElyralab/MuseTalk
- SoulX FlashTalk code: https://github.com/Soul-AILab/SoulX-FlashTalk
- SoulX FlashTalk 14B: https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B
- Chinese wav2vec2: https://huggingface.co/TencentGameMate/chinese-wav2vec2-base

#### 2. 启动 Wav2Lip OmniRT

CUDA GPU:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

Ascend 910B NPU:

启动 NPU 服务前先 source CANN

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
```

> 如果你的 CANN 路径不同，把上面的路径替换成实际的 `set_env.sh`。

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

#### 3. 启动 MuseTalk OmniRT

MuseTalk 的编排方式和 Wav2Lip / FlashTalk 一致：推理与服务都在 OmniRT，OpenTalking 只通过 `--omnirt` 访问统一的 audio2video 接口。和 Wav2Lip 的单层 `serve-avatar-ws` 不同，MuseTalk helper 会先启动 WebSocket backend，再启动 OmniRT gateway。

CUDA GPU：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda
```

如果 `9000` 或默认 GPU 已被占用，直接改端口或卡号。例如：

```bash
export CUDA_VISIBLE_DEVICES=4
bash scripts/quickstart/start_omnirt_musetalk.sh \
  --device cuda \
  --port 9001 \
  --musetalk-port 8766
```

Ascend 910B NPU：

启动 NPU 服务前先 source CANN

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
```

> 如果你的 CANN 路径不同，把上面的路径替换成实际的 `set_env.sh`。

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_musetalk.sh --device npu
```

验证：

```bash
curl http://127.0.0.1:9000/v1/audio2video/models
```

`musetalk` 应该返回 `connected: true`。

这个 helper 会做两件事：

- 启动 MuseTalk WS backend，默认 `127.0.0.1:8766`
- 启动 OmniRT gateway，默认 `0.0.0.0:9000`

环境已经装好后，重复启动可以加 `--skip-install`。

#### 4. 启动 FlashTalk OmniRT（可选）

FlashTalk 比 Wav2Lip 更重。建议先跑通 Wav2Lip，再启动 FlashTalk。

CUDA GPU：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
```

Ascend 910B NPU：

启动 NPU 服务前先 source CANN

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
```

> 如果你的 CANN 路径不同，把上面的路径替换成实际的 `set_env.sh`。

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu --nproc 8
```

验证：

```bash
curl http://127.0.0.1:9000/v1/audio2video/models
```

`flashtalk` 应该返回 `connected: true`。

#### 5. 启动 OpenTalking 真实模型模式并连接 OmniRT

保持第 2、3 或 4 步启动的 OmniRT 服务运行，然后启动 OpenTalking API 和前端：

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

如需自定义端口：

```bash
bash scripts/quickstart/start_all.sh \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8010 \
  --web-port 5180
```

如果 OmniRT 在远端 GPU / NPU 机器，把 `--omnirt` 改成 `http://<gpu-or-npu-server-ip>:9000`：

```bash
bash scripts/quickstart/start_all.sh \
  --omnirt http://<gpu-or-npu-server-ip>:9000 \
  --api-port 8010 \
  --web-port 5180
```

默认浏览器地址是 `http://localhost:5173`；如果使用了 `--web-port 5180`，则访问 `http://localhost:5180`。

选择 `wav2lip`、`musetalk` 或 `flashtalk`。真实模型卡片应显示 **已连接**；`mock / 无驱动模式` 会显示 **无需连接**。

查看或停止 helper 管理的服务：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/status.sh
bash scripts/quickstart/stop_all.sh
```

### 路径 3：高质量私有化部署

目标：运行 FlashTalk 14B / FlashHead 等高质量模型，面向私有化或生产环境。仍使用 `OMNIRT_ENDPOINT`，但建议启用 API / Worker 分离、Redis 和独立前端构建。

```env
OMNIRT_ENDPOINT=http://<gpu-host>:9000
OMNIRT_API_KEY=sk-omnirt-xxx           # 如果你的 OmniRT 开启鉴权
OPENTALKING_DEFAULT_MODEL=flashtalk     # 或 flashhead
OPENTALKING_REDIS_URL=redis://redis:6379/0
```

```bash
opentalking-api &
opentalking-worker &
cd apps/web && npm ci && npm run build
```

Ascend 910B 可使用薄部署 wrapper：

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/deploy_ascend_910b.sh
```

### 三种路径速览

| 路径 | 推理 backend | GPU | 适合场景 |
| --- | --- | --- | --- |
| 快速体验 | 内置 Mock | 不需要 | 首次运行、前端调试、主链路验证 |
| 轻量模型验证 | Local / direct WS / OmniRT lightweight model | 入门级 GPU 起 | Avatar / 模型适配开发 |
| 高质量部署 | OmniRT + FlashTalk / FlashHead | 4090 / 910B | 私有化、生产、高质量画面 |

### 支持模型

| 模型 | 输入 | OpenTalking 集成方式 | 推荐路径 |
| --- | --- | --- | --- |
| `mock` | 参考图 | 内置静态帧 | 快速体验 |
| `wav2lip` | frames + audio | 可插拔轻量口型 backend；local / direct backend 优先，OmniRT 作为兼容路径 | 轻量模型验证 |
| `musetalk` | full frames + audio | 可插拔轻量 talking-head backend | 轻量模型验证 |
| `soulx-flashtalk-14b` | portrait + audio | OmniRT 高质量 FlashTalk | 高质量部署 |
| `soulx-flashhead-1.3b` | portrait + audio | direct FlashHead WebSocket | 高质量部署 |

更完整的权重下载、国内源、Docker Compose、故障排查和模型 backend 配置见 [模型部署文档](docs/zh/model-deployment/index.md) 与 [部署文档](docs/zh/user-guide/deployment.md)。


## Roadmap

- [x] **实时数字人基础体验**
  Web 控制台、LLM 对话、TTS、字幕事件、WebRTC 音视频播放。

- [ ] **更自然的实时对话（进行中）**
  支持打断、会话状态、低延迟响应、音画同步和异常恢复。

- [x] **OmniRT 模型服务接入**
  OmniRT 作为重模型、多卡和远端推理 backend 接入；轻量模型保留本地或单模型直连扩展空间。

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

- [快速开始](docs/zh/user-guide/quickstart.md)
- [模型](docs/zh/model-deployment/index.md)（权重下载、国内源、启动、验证）
- [架构说明](docs/zh/developer-guide/architecture.md)
- [配置说明](docs/zh/user-guide/configuration.md)
- [部署文档](docs/zh/user-guide/deployment.md)（Docker Compose、分布式部署）
- [模型适配](docs/zh/developer-guide/model-adapter.md)
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
