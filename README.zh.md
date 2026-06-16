<h1 align="center">OpenTalking</h1>

<p align="center">
  <b>面向实时对话的开源数字人产线：LLM、TTS、WebRTC、角色音色与可插拔模型后端</b>
</p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="https://datascale-ai.github.io/opentalking/latest/">文档站</a> ·
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
  <a href="https://www.opentalking.net/#github">
    <img src="https://img.shields.io/badge/Visit%20OpenTalking%20Website-00A6D6?style=for-the-badge&logo=googlechrome&logoColor=white" alt="Visit OpenTalking Website">
  </a>
</p>

<p align="center">
  <a href="#webui-与效果展示">效果展示</a> ·
  <a href="#选择部署路线">部署路线</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#模型支持">模型支持</a> ·
  <a href="#能力进展与-roadmap">Roadmap</a> ·
  <a href="#文档与社区">文档与社区</a>
</p>

---

## 项目简介

OpenTalking 是一个开源实时数字人对话编排框架，目标是构建 **数字人对话产品** 的核心链路：前端交互、会话状态、LLM 回复、STT、TTS / 音色选择、打断控制、字幕事件、WebRTC 音视频播放，以及本地或远端模型服务调用。

OpenTalking 更偏向可落地的数字人产线：前端 WebUI、形象 / 音色资产库、知识库、记忆、多会话状态、LLM / STT / TTS provider、WebRTC 播放和模型后端都在同一套工程里组织。你可以从最轻量的 Mock 模式开始，也可以接入本地 QuickTalk / Wav2Lip，或通过 OmniRT 使用 FlashTalk、FasterLivePortrait 等更高质量或更复杂的模型工作流。

- **快速体验**：`mock / 无驱动模式`，适合第一次打通 API、TTS、WebRTC 全链路。
- **实时对话**：接入 `QuickTalk`、`Wav2Lip`、`FlashTalk` 等模型，完成可交互数字人对话。
- **视频创作与克隆**：复用 FasterLivePortrait runtime，支持语音/文字驱动视频创作和摄像头/上传视频驱动的视频克隆。
- **私有化部署**：支持本地 STT/TTS、OpenAI-compatible LLM、知识库 / 记忆、OmniRT 远端推理和 Docker / 分布式部署。

更多文档：

- 在线文档：<https://datascale-ai.github.io/opentalking/latest/>
- 英文文档：<https://datascale-ai.github.io/opentalking/latest/en/>

## WebUI 与效果展示

OpenTalking 提供 Web 服务界面，用于管理数字人对话链路：可以选择或新建数字人物，配置音色、LLM、TTS、STT 和数字人驱动模型，查看模型连接状态，并在同一页面完成实时对话、字幕和音视频播放验证。

![OpenTalking WebUI](docs/assets/images/WebUI.png)

### Demo 视频

以下是 OpenTalking 典型场景演示视频，覆盖实时对话、视频创作和视频克隆三类前端工作流。

<table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <th align="center" colspan="3">A. 实时对话</th>
  </tr>
  <tr>
    <td align="center" valign="top" width="33%">
      <b>电商带货</b><br/>
      <video src="https://github.com/user-attachments/assets/4646f29d-f773-4f95-84a9-8128ea97ac14" controls preload="metadata" width="248" height="441"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>陪伴案例</b><br/>
      <video src="https://github.com/user-attachments/assets/6e80d2ac-36a0-41bb-8394-26e0c1121cb6" controls preload="metadata" width="248" height="441"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>新闻主播</b><br/>
      <video src="https://github.com/user-attachments/assets/ff7ba86b-927a-46f9-91a6-cfed5d332bda" controls preload="metadata" width="248" height="441"></video><br/>
    </td>
  </tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <th align="center" colspan="3">B. 视频创作</th>
  </tr>
  <tr>
    <td align="center" valign="top" width="33%">
      <b>语音 drive</b><br/>
      <video src="https://github.com/user-attachments/assets/d2b93d0c-2ee6-409f-84d9-79d109d8592c" controls preload="metadata" width="248" height="140"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>文字 drive</b><br/>
      <video src="https://github.com/user-attachments/assets/d1d4df8d-c599-4c6d-b61c-eec361e9556c" controls preload="metadata" width="248" height="140"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>克隆音色 drive</b><br/>
      <video src="https://github.com/user-attachments/assets/87b3efc4-d54a-4d2a-8d70-c37834154518" controls preload="metadata" width="248" height="140"></video><br/>
    </td>
  </tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <th align="center" colspan="2">C. 视频克隆</th>
  </tr>
  <tr>
    <td align="center" valign="top" width="50%">
      <b>摄像头实时模仿</b><br/>
      <video src="https://github.com/user-attachments/assets/cd8c9e7b-66a6-46c8-b6c8-61632ce1a712" controls preload="metadata" width="386" height="217"></video><br/>
    </td>
    <td align="center" valign="top" width="50%">
      <b>上传视频模仿</b><br/>
      <video src="https://github.com/user-attachments/assets/5e8a5ae9-e39e-48ee-8c41-930369edc6b4" controls preload="metadata" width="386" height="217"></video><br/>
    </td>
  </tr>
</table>

## 选择部署路线

OpenTalking 的 **编排层**（API / Worker / 前端）和 **数字人合成后端**（`mock`、`local`、`direct_ws` 或 [OmniRT](https://github.com/datascale-ai/omnirt)）可以独立部署。第一次接触项目时，建议先用 Mock 模式跑通完整链路，再按显卡、模型和私有化需求切换到真实视频渲染模型。

| 路线 | 推荐模型 / 后端 | 设备参考 | 适合场景 | 详细文档 |
| --- | --- | --- | --- | --- |
| 快速体验 | `mock` | CPU / 无 GPU | 不下载模型权重，先验证 API、LLM、TTS、WebRTC 与浏览器播放链路 | [快速开始](docs/zh/user-guide/quickstart.md) |
| 入门验证 | `quicktalk` / `wav2lip` | RTX 3050 Laptop、RTX 3060、RTX 4060 | 能跑通真实视频渲染，适合功能演示和部署验证；低显存设备建议降低分辨率 | [QuickTalk](docs/zh/model-deployment/quicktalk.md) / [Wav2Lip](docs/zh/model-deployment/wav2lip-local.md) |
| 消费级显卡单机 | `quicktalk` / `wav2lip` / `musetalk` | RTX 3090、RTX 4090 | 更接近实时体验，适合本地 demo、私有化验证和轻量生产前评估 | [模型部署](docs/zh/model-deployment/index.md) |
| 全本地私有化 | `sensevoice` + `local_cosyvoice` + `quicktalk` | RTX 3090 / 4090 或同级 GPU | STT、TTS、视频驱动都走本地模型，减少外部依赖 | [本地 STT/TTS + QuickTalk](docs/zh/model-deployment/local-quicktalk-audio.md) |
| 高质量远端推理 | `flashtalk` / `flashhead` / `fasterliveportrait` + OmniRT | 多卡 GPU、Ascend 910B2、远端 GPU 服务 | 多卡、GPU/NPU、生产隔离、更高画质或视频克隆 | [FlashTalk](docs/zh/model-deployment/flashtalk.md) / [FasterLivePortrait](docs/zh/model-deployment/fasterliveportrait.md) |
| Docker / 生产部署 | API、Web、Worker、外部模型服务分离 | 单机 GPU、远端 GPU、分布式集群 | 服务化部署、远端 GPU、分布式和生产验证 | [部署文档](docs/zh/user-guide/deployment.md) |

## 快速开始

适用：第一次接触项目，不下载视频模型权重，先用 Mock 模式跑通产品链路。数字人画面使用内置静态帧，LLM 回复、流式 TTS、字幕事件和 WebRTC 传输仍是完整链路。

```bash
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

uv sync --extra dev --python 3.11
source .venv/bin/activate
cp .env.example .env
```

编辑 `.env`，至少配置 LLM；TTS 默认可使用不需要 key 的 `edge` 语音。LLM、STT、TTS 是独立 provider，常见配置见 [配置说明](docs/zh/user-guide/configuration.md) 和 [LLM / STT 文档](docs/zh/model-deployment/llm-stt.md)。

```bash
bash scripts/start_unified.sh --mock
```

默认前端地址是 `http://localhost:5173`。如果需要指定端口：

```bash
bash scripts/start_unified.sh --mock --api-port 8210 --web-port 5280
```

停止服务：

```bash
bash scripts/quickstart/stop_all.sh
```

### 真实模型启动入口

完成 Mock 验证后，再按机器条件选择真实模型路线。权重下载、目录结构、国内镜像、校验、故障排查都放在文档站中维护，README 只保留启动入口：

```bash
# 本地 QuickTalk：消费级显卡单机路线
export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$PWD/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280

# 远端 OmniRT / FlashTalk：高质量或多卡路线
bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --api-port 8210 \
  --web-port 5280 \
  --omnirt http://<gpu-server>:9000
```

更多入口：

- [QuickTalk 本地部署](docs/zh/model-deployment/quicktalk.md)
- [Wav2Lip 本地部署](docs/zh/model-deployment/wav2lip-local.md)
- [FasterLivePortrait / JoyVASA](docs/zh/model-deployment/fasterliveportrait.md)
- [视频克隆使用说明](docs/zh/usage/webui/video-clone.md)
- [WebUI 使用说明](docs/zh/usage/webui/basic.md)
- [Docker Compose 与生产部署](docs/zh/user-guide/deployment.md)

## 模型支持

| 模型 | 输入 | 推荐 backend | 资源建议 |
| --- | --- | --- | --- |
| `mock` | 参考图 / 静态帧 | `mock` | 不需要 GPU |
| `quicktalk` | template video + audio | `local` | CUDA GPU，推荐 3090 / 4090 |
| `wav2lip` | 参考图 / frames + audio | `local` / `omnirt` | `>= 8 GB` GPU / NPU memory |
| `musetalk` | full frames + audio | `omnirt` / `local` | `>= 12 GB` GPU memory |
| `soulx-flashtalk-14b` | portrait + audio | `omnirt` | 多卡 GPU / NPU |
| `soulx-flashhead-1.3b` | portrait + audio | `omnirt` | 多卡 GPU / NPU |
| `fasterliveportrait` | portrait / driving video / audio | `omnirt` | 单卡实时头像贴回、视频创作、视频克隆 |

### 消费级显卡参考

| 模型 | 硬件 | 输入 | 输出 | 显存占用 | 生成吞吐 |
| --- | --- | --- | --- | --- | --- |
| `quicktalk` | RTX 3090 | template video + audio | 720x900 / 25fps | 约 3.8 GiB | 约 35 fps |

更多权重下载、Docker、故障排查和模型配置见 [模型部署索引](docs/zh/model-deployment/index.md)。

### 云端模型 API：Atlas Cloud

<p align="center">
  <a href="https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=opentalking">
    <img src="docs/assets/images/atlas-cloud-logo.png" alt="Atlas Cloud" width="200">
  </a>
</p>

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=opentalking)** 是一个全模态 AI 推理平台，用一套 API 即可访问视频生成、图像生成和 LLM，无需分别对接多家厂商，一次接入即可统一调用全模态的 300+ 精选模型。

OpenTalking 的 LLM 走 OpenAI-compatible 接口，把 `OPENTALKING_LLM_BASE_URL` 指向 `https://api.atlascloud.ai/v1` 即可直接使用 Atlas 托管的 DeepSeek / Qwen 等模型，配置见 [LLM 与 STT](docs/zh/model-deployment/llm-stt.md)。更多预算友好的 API 方案见 Atlas Cloud [coding plan](https://www.atlascloud.ai/console/coding-plan)。

## 能力进展与 Roadmap

- [ ] **更自然的实时对话体验**
  继续打磨打断、低延迟响应、音画同步、长会话恢复和运行状态可见性。

- [ ] **消费级显卡多模型路线**
  完善 QuickTalk / Wav2Lip / MuseTalk local 的资产检查、预热、缓存复用、低显存参数和更多 3090 / 4090 / WSL2 benchmark，并继续补齐 FasterLivePortrait 的视频创作与视频克隆评测数据。

- [ ] **Windows / WSL2 一键化部署**
  在现有 Windows 部署文档和测试记录基础上，继续降低模型下载、运行时安装、环境检查和诊断门槛。

- [ ] **高质量私有化部署**
  完善外部 OmniRT 推理服务、多模型 endpoint、容量调度、健康检查、生产监控和 GPU / NPU 部署指引。

- [ ] **更多云端语音与多模态 provider**
  在现有 OpenAI-compatible、DashScope、Xiaomi MiMo 等 profile 基础上，继续扩展可插拔 STT / TTS / LLM provider、统一前端选择体验和 provider 级健康检查。

- [ ] **Agent、记忆与平台能力**
  继续产品化资产库、知识库、记忆、多会话调度、工具调用和 OpenClaw / 外部 Agent 对接，并逐步补齐观测指标、安全合规、授权音色和合成内容标识。

### 近期进展

- **2026-06-12：QuickTalk 本地资产修复与 Apple Silicon 支持**
  梳理 QuickTalk 本地权重、HuBERT、InsightFace 等资产路径，补充缺失资产检查、缓存准备和健康检查；新增 Apple Silicon 部署文档，支持在 macOS arm64 上使用 `quicktalk-cpu` 与 MPS / CPU 路线验证。

- **2026-06-12：IndexTTS、QuickTalk 与 FlashTalk 视频创作增强**
  增加本地 IndexTTS 与 OmniRT IndexTTS provider、系统音色、音色预览和音色标签；完善 QuickTalk / IndexTTS 视频创作链路，并加入 FlashTalk reference video 生成和默认 reference driver。

- **2026-06-02/10：Persona Package、知识库检索与角色记忆**
  新增 Persona Package API / CLI / WebUI 入口，可把角色设定、知识材料和提示词打包复用；接入 LightRAG 知识检索、会话级知识选择、角色记忆面板，以及 BM25 / mem0 / SQLite 等记忆 provider。

- **2026-06-05：资产库与知识库工作流**
  扩展 WebUI 资产库，把形象资产、知识库材料、会话选择和 Agent 上下文构建串起来；同时补齐音频 / 视频导出，让演示、复盘和素材沉淀可以在同一套工作台完成。

- **2026-06-05/06：OpenAI-compatible 音频接口与 MuseTalk 部署优化**
  新增 OpenAI-compatible STT / TTS 适配层、Xiaomi MiMo STT / TTS / voice clone profile、前端 provider 选择与音色列表，并把 `.env.example` 整理为 LLM / STT / TTS 独立 profile 模板。
  同期优化 MuseTalk local / OmniRT 部署文档、资产准备脚本和 quickstart 启动脚本，降低 MuseTalk 路线的准备成本。

- **2026-06-04：FasterLivePortrait 视频创作与视频克隆**
  新增 FasterLivePortrait 视频创作参数面板、视频克隆页面、自定义 source 资产上传、摄像头 / 上传视频 driving 输入和文档截图，复用 OmniRT + FasterLivePortrait runtime 路线。

- **2026-06-03：Web 录制导出、资产库与视频工作流**
  新增 Web 录制导出、导出存储、视频创作入口和资产库工作台，打通从实时对话、素材管理到视频生成的基础流程。

- **2026-06-12/13：官网分析、GitHub 流量统计与部署文档**
  补充官网英文页、部署路线展示、访问分析、GitHub traffic 统计、图表样式和统计周期修复；新增 Windows 部署中的 WSL2 网络模式选择指南，并持续更新 README 演示视频与文档站入口。

- **更早基础能力：实时对话主链路与模型 backend 解耦**
  已建立 Web 控制台、LLM 对话、TTS、字幕事件、WebRTC 音视频播放、Avatar 资产预热缓存、统一 audio2video runner，以及 `mock` / `local` / `direct_ws` / `omnirt` 等可插拔模型后端。

## 文档与社区

- [快速开始](docs/zh/user-guide/quickstart.md)
- [模型](docs/zh/model-deployment/index.md)（权重下载、国内源、启动、验证）
- [架构说明](docs/zh/developer-guide/architecture.md)
- [配置说明](docs/zh/user-guide/configuration.md)
- [部署文档](docs/zh/user-guide/deployment.md)（Docker Compose、分布式部署）
- [模型适配](docs/zh/developer-guide/model-adapter.md)
- [贡献指南](CONTRIBUTING.md)（开发环境、CLI 工具、ruff / mypy / pytest）

欢迎加入 QQ 交流群，讨论实时数字人、FlashTalk、OmniRT、模型部署和产品场景。

<p align="center">
  <img src="docs/assets/images/qq_group_qrcode.png" alt="AI 数字人交流群二维码" width="280">
</p>

<p align="center">
  <b>AI 数字人交流群</b> · 群号：<code>1103327938</code>
</p>

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
