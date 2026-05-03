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

- **快速体验**：`demo-avatar / wav2lip`，不需要独立模型服务，适合第一次验证 API、TTS、WebRTC 和前端。
- **轻量适配验证**：`wav2lip / musetalk`，用于验证 Avatar 资产格式、模型适配器和端到端编排。
- **高质量部署**：通过 [OmniRT](https://github.com/datascale-ai/omnirt) 接入 FlashTalk-compatible WebSocket，面向消费级 GPU 和企业私有化推理服务。

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
  <img src="images/qq_group_qrcode.png" alt="AI 数字人交流群二维码" width="280">
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

![OpenTalking Architecture](images/opentalking_architecture.png)

## 项目结构

```text
opentalking/
├── src/opentalking/
│   ├── core/         # 配置、接口协议、类型定义
│   ├── engine/       # FlashTalk 兼容本地推理路径
│   ├── server/       # 分布式 WebSocket 推理服务
│   ├── models/       # Avatar 模型适配器
│   ├── worker/       # 会话编排
│   ├── llm/          # OpenAI 兼容 LLM 客户端
│   ├── tts/          # TTS 适配器
│   ├── rtc/          # WebRTC 传输
│   ├── voices/       # 音色 profile 和 provider 接入
│   └── events/       # SSE 和运行时事件
├── apps/
│   ├── api/          # FastAPI 服务
│   ├── unified/      # 单进程模式
│   ├── web/          # React 前端
│   └── cli/          # 模型下载、视频生成、demo 工具
├── configs/          # YAML 配置示例
├── docker/           # Docker Compose
├── scripts/          # 启动和部署脚本
├── tests/            # 单元测试 / 集成测试
└── docs/             # 文档
```

## 快速开始

默认快速体验使用 `demo-avatar / wav2lip`，`OPENTALKING_FLASHTALK_MODE=off`，不需要先下载 FlashTalk 权重或启动 OmniRT。LLM / STT 可走阿里云百炼 API，TTS 默认 Edge TTS，无需 key。完整说明见 [docs/quickstart.md](docs/quickstart.md)。

### 1. 准备 OpenTalking 编排层

```bash
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

在 [bailian.console.aliyun.com](https://bailian.console.aliyun.com/) 申请百炼 API Key，然后在 `.env` 里补上密钥；其它字段保持默认即可：

```env
# 快速体验：不启用 FlashTalk，默认使用 demo-avatar / wav2lip
OPENTALKING_DEFAULT_MODEL=wav2lip
OPENTALKING_FLASHTALK_MODE=off

# LLM：百炼 OpenAI-compatible endpoint
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-dashscope-key
OPENTALKING_LLM_MODEL=qwen-flash

# STT：百炼 Paraformer realtime
DASHSCOPE_API_KEY=sk-your-dashscope-key
OPENTALKING_STT_MODEL=paraformer-realtime-v2

# TTS：默认 Edge TTS，无需 key
OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural

# 可选：切到百炼 Qwen realtime TTS（复用上面的 DASHSCOPE_API_KEY）
# OPENTALKING_TTS_PROVIDER=dashscope
# OPENTALKING_QWEN_TTS_MODEL=qwen3-tts-flash-realtime
```

### 2. 启动 OpenTalking 与前端

开两个终端：

```bash
# 终端 1：后端
cd opentalking
source .venv/bin/activate
bash scripts/start_unified.sh

# 终端 2：前端
cd opentalking/apps/web
npm ci
npm run dev -- --host 0.0.0.0
```

打开 `http://localhost:5173`。

环境要求：Python ≥ 3.9、Node.js ≥ 18、FFmpeg；分布式模式额外需要 Redis。

### 三条使用路径

| 路径 | 推荐对象 | 配置 | 说明 |
| --- | --- | --- | --- |
| 快速体验 | 第一次运行、普通用户 | `.env.example`，`OPENTALKING_FLASHTALK_MODE=off`，`OPENTALKING_DEFAULT_MODEL=wav2lip` | 不需要独立模型服务，默认 `demo-avatar / wav2lip` |
| 轻量适配验证 | 模型/Avatar 适配开发 | `wav2lip` 或 `musetalk` | MuseTalk 当前偏适配验证和准备资产体验 |
| 高质量部署 | 私有化、生产验证、高质量数字人 | `.env.flashtalk.example`，FlashTalk + OmniRT | 见 [FlashTalk + OmniRT 部署](docs/flashtalk-omnirt.md) |

### 模型支持

| 模型 | 输入 | OpenTalking 接入 |
| --- | --- | --- |
| `wav2lip`（默认快速体验） | frames + audio | 轻量口型同步 demo / fallback；无需独立模型服务 |
| `musetalk` | full frames + audio | 轻量 talking-head 适配验证 |
| `soulx-flashtalk-14b` | portrait + audio | OmniRT FlashTalk WebSocket；使用 `.env.flashtalk.example` 启用 |
| `soulx-flashhead-1.3b` | portrait + audio | OmniRT 当前仅暴露 HTTP `/v1/generate`，OpenTalking WebSocket 适配计划中 |
| `soulx-liveact-14b` | portrait + audio | 同上 |


## Roadmap

- [x] **实时数字人基础体验**  
  Web 控制台、LLM 对话、TTS、字幕事件、WebRTC 音视频播放。

- [ ] **更自然的实时对话（进行中）**  
  支持打断、会话状态、低延迟响应、音画同步和异常恢复。

- [ ] **OmniRT 模型服务接入**  
  通过 OmniRT 统一调用 FlashTalk、轻量 talking-head、ASR、语音合成和音色服务。

- [ ] **消费级显卡可用**  
  面向 RTX 3090 / 4090 提供轻量模型、单卡实时配置和端到端 benchmark。

- [ ] **高质量私有化部署（进行中）**  
  面向企业私有化场景，支持外部 OmniRT 推理服务、容量调度、健康检查和生产监控；昇腾 910B 等企业级 GPU/NPU 路线已在构建中。

- [ ] **自定义角色和音色**  
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
