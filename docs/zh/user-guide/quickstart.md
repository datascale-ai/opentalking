# 快速上手

本指南采用 mock 合成路径完成一次端到端数字人会话。mock 路径不依赖 GPU，亦无需预先下载
模型权重，适用于首次安装与 CI 环境。

完成本指南后，将在 `http://localhost:5173` 提供 Web 入口，音频输入通过语音识别、大语言
模型、语音合成三层流水线处理，合成视频帧经 WebRTC 推流到浏览器。

## 前置条件

| 组件 | 最低版本 | 用途 |
|------|---------|------|
| Python | 3.9（建议 3.11） | 服务运行时 |
| Node.js | 18 | 前端构建工具链 |
| ffmpeg | 较新稳定版 | TTS 流水线的音频解码 |
| DashScope API Key | — | 默认大语言模型（`qwen-flash`）与语音识别（`paraformer-realtime-v2`）所需。申请地址：[bailian.console.aliyun.com](https://bailian.console.aliyun.com) |

本指南不依赖 GPU 与 NPU。仅在 [第 5 步](#5-talking-head) 切换到真实 talking-head 模型时
才需要 CUDA 或昇腾硬件。

## 1. 从源码安装

```bash title="终端"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

## 2. 配置必填凭证

在 `.env` 中配置以下两个变量。其余配置项均具有可工作的默认值，无需调整。

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

两个变量必须设置为同一把 DashScope API Key。`OPENTALKING_LLM_API_KEY` 用于大语言模型
客户端，`DASHSCOPE_API_KEY` 由 DashScope SDK 直接读取，用于语音识别。

!!! note "其它大语言模型 provider"
    任意 OpenAI 兼容 endpoint 均可替代 DashScope。切换 provider 时同时调整
    `OPENTALKING_LLM_BASE_URL` 与 `OPENTALKING_LLM_MODEL`。详见
    [配置](configuration.md#1-llm-stt-tts)。

## 3. 启动服务

```bash title="终端"
bash scripts/quickstart/start_all.sh --mock
```

该脚本启动两个进程：

1. **OpenTalking 单进程服务**，监听 `http://127.0.0.1:8000`，提供会话、Avatar、SSE 与
   WebRTC 信令的 FastAPI 接口。
2. **前端开发服务器**，监听 `http://localhost:5173`，由 Vite 构建并服务 React 客户端。

mock 合成后端在进程内运行，不依赖 OmniRT 或外部推理服务。

## 4. 发起会话

在 Chromium 内核浏览器中访问 <http://localhost:5173>。WebRTC 为必需特性。

1. 在 Avatar 列表中选择 `demo-avatar`。
2. 在模型选择器中选择 `mock`。
3. 点击麦克风图标并开始说话。界面将实时展示语音识别结果、模型输出、合成音频与渲染视频。

mock 后端为每个音频片段返回固定占位图，便于在接入真实模型之前完成完整流水线验证。

## 5. 启用 talking-head 模型

mock 路径验证通过后，可切换至真实 talking-head 模型。各模型的权重下载、国内源入口、
启动命令和验证流程见 [模型](../model-deployment/index.md)。最短路径如下：

=== "wav2lip"

    轻量级唇形同步模型，单张 NVIDIA 3090 级 GPU 即可运行。推荐部署方向是本地或单模型
    直连 backend；当前 quickstart 先使用 OmniRT 作为可运行兼容路径，直到本地 Wav2Lip
    adapter 内置完成。

    ```bash title="终端"
    # 在独立终端运行；OmniRT 仓库须与 opentalking/ 处于同级目录。
    bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
    ```

    在 `.env` 中追加：

    ```env
    OMNIRT_ENDPOINT=http://127.0.0.1:9000
    ```

    重启 `start_all.sh`，在模型选择器中切换至 `wav2lip`。国内下载入口与完整权重目录见
    [模型 → Wav2Lip](../model-deployment/talking-head.md#wav2lip)。

=== "FlashTalk"

    SoulX FlashTalk-14B 端到端 talking-head 模型，需 NVIDIA 4090 或 A100 级 GPU。

    ```bash title="终端"
    bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda
    ```

    配置 OmniRT endpoint：

    ```env
    OMNIRT_ENDPOINT=http://127.0.0.1:9000
    ```

    在模型选择器中选择 `flashtalk`。FlashTalk 权重目录、CUDA/Ascend 启动与国内镜像
    入口见 [模型 → FlashTalk](../model-deployment/talking-head.md#flashtalk)。

=== "昇腾 910B"

    昇腾 NPU 评估建议在宿主机 CANN 环境下源码安装。详见
    [源码安装 → 昇腾 910B](install-from-source.md#ascend-910b)。

## 6. 验证与停止服务

检查服务运行状态：

```bash title="终端"
bash scripts/quickstart/status.sh
```

输出包含单进程服务、前端与 OmniRT 的状态信息。停止所有由 quickstart 启动的进程：

```bash title="终端"
bash scripts/quickstart/stop_all.sh
```

## 故障排查

下表列出安装过程中的常见问题与对应处理方式。

| 现象 | 处理方式 |
|------|---------|
| TTS 解码时出现 `ffmpeg: not found` | 安装 ffmpeg。macOS：`brew install ffmpeg`；Debian/Ubuntu：`apt install ffmpeg`。 |
| 大语言模型返回 HTTP 401 | 确认 `OPENTALKING_LLM_API_KEY` 与 `DASHSCOPE_API_KEY` 均已设置且为同一把 DashScope key。 |
| 浏览器提示不支持 WebRTC | 使用 Chromium 内核浏览器。Safari 需将 `OPENTALKING_API_HOST` 设为 `127.0.0.1` 并匹配 CORS origin。 |
| 端口 8000 被占用 | 覆盖默认端口：`bash scripts/quickstart/start_all.sh --mock --api-port 8010 --web-port 5180`。 |
| OmniRT 启动后立即退出 | 检查 OmniRT 启动脚本输出中的日志路径，通常位于 `~/logs/omnirt-wav2lip.log`。 |

## 下一步

- [配置](configuration.md) —— 所有环境变量与 YAML 字段的参考。
- [模型](../model-deployment/index.md) —— 每个模型 backend 的权重下载、启动与验证。
- [部署](deployment.md) —— 多进程部署、Docker Compose 与生产建议。
- [架构](../developer-guide/architecture.md) —— 系统内部结构与事件总线 schema。
- [API 参考](../api-reference/index.md) —— 完整的 HTTP 与 WebSocket 端点文档。
