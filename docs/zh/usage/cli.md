# 命令行工具

命令行工具用于启动服务、准备资产、切换模型后端和做性能验证。它更偏开发和部署联调：当你需要复现问题、固定端口、接入远端推理服务，或者把启动流程写进脚本时，应该优先使用命令行。

## 什么时候使用命令行工具

建议在这些场景使用命令行：

- 第一次验证环境是否安装完整。
- 启动 Mock、本地 QuickTalk 或 OmniRT 后端。
- 调整 API / WebUI 端口，避免和本机已有服务冲突。
- 为 Wav2Lip 准备图片或视频 Avatar 资产。
- 对 QuickTalk 的首帧时间、渲染 FPS、初始化耗时做基准测试。

如果你只想体验交互流程，可以直接从[快速开始](../quick-start/index.md)进入 WebUI。

## 服务启动命令

### `opentalking-unified`

`opentalking-unified` 是当前最推荐的本地开发入口。它会在一个进程里启动 API、会话编排和内存队列，适合本机调试和快速验证。

```bash
uv run opentalking-unified
```

常见配套环境变量：

```bash
export OPENTALKING_AVATARS_DIR=./examples/avatars
export OPENTALKING_DEFAULT_MODEL=quicktalk
```

实际使用时更推荐通过 `scripts/start_unified.sh` 包装启动，因为脚本会同时拉起 WebUI，并处理端口、后端和环境文件。

### `opentalking-api`

`opentalking-api` 只启动 API 服务，适合你希望把 API、Worker、前端拆开运行时使用。

```bash
uv run opentalking-api
```

这种模式更接近生产拆分，但本地调试成本也更高。除非你明确需要独立 Worker，否则优先使用 unified 模式。

### `opentalking-worker`

`opentalking-worker` 用于独立消费任务队列并运行模型推理。

```bash
uv run opentalking-worker
```

当你要验证多 Worker、队列消费、GPU 绑定或更接近生产拓扑的部署方式时，再使用这个入口。

## 快速启动脚本

### `scripts/start_unified.sh`

这是当前最实用的启动脚本，会启动 OpenTalking API / unified 后端和 WebUI。

Mock 模式：

```bash
bash scripts/start_unified.sh --mock
```

本地 QuickTalk：

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

远端 OmniRT：

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --omnirt http://127.0.0.1:9000
```

脚本启动后会在终端输出 WebUI 地址，默认是 `http://127.0.0.1:5173`。

### `scripts/quickstart/start_mock.sh`

`start_mock.sh` 是更聚焦的 Mock 快速入口，适合只想验证前后端流程的情况。

```bash
bash scripts/quickstart/start_mock.sh
```

Mock 模式不会加载真实模型，也不需要下载模型权重。它适合排查 WebUI、会话状态、前端资源和基础 API 是否正常。

### `scripts/quickstart/status.sh`

启动后可以用状态脚本检查 API、WebUI 和 OmniRT 是否在线。

```bash
bash scripts/quickstart/status.sh
```

如果你改过端口，可以带上对应端口：

```bash
bash scripts/quickstart/status.sh --api-port 8001 --web-port 5174
```

### `scripts/quickstart/stop_all.sh`

停止 quickstart 脚本启动的服务：

```bash
bash scripts/quickstart/stop_all.sh
```

如果本机有多个 OpenTalking 服务实例，建议先用 `status.sh` 确认端口和 PID，再停止。

## Avatar 处理脚本

### `prepare_wav2lip_image_asset.py`

把一张图片处理成 Wav2Lip 可用的内置 Avatar 目录。

```bash
uv run python scripts/prepare_wav2lip_image_asset.py \
  --source-image ./assets/my-avatar.png \
  --out ./examples/avatars/my-avatar \
  --avatar-id my-avatar \
  --name "My Avatar"
```

脚本会生成 `manifest.json`、`reference.png`、`preview.png` 和首帧素材，并写入口型检测相关 metadata。

### `prepare_wav2lip_video_asset.py`

把一段视频拆帧并生成 Wav2Lip Avatar 目录。

```bash
uv run python scripts/prepare_wav2lip_video_asset.py \
  --source-video ./assets/my-avatar.mp4 \
  --out ./examples/avatars/my-video-avatar \
  --avatar-id my-video-avatar \
  --name "My Video Avatar" \
  --max-frames 125
```

视频素材更适合保留自然头部姿态和背景变化，但准备时间更长，也更依赖源视频质量。

## Benchmark / 调试脚本

### `opentalking-quicktalk-bench`

`opentalking-quicktalk-bench` 用于测量 QuickTalk 的初始化耗时、首帧时间、渲染 FPS 和输出视频生成情况。

```bash
uv run opentalking-quicktalk-bench \
  --asset-root ./examples/avatars/quicktalk-daytime \
  --template-video ./examples/avatars/quicktalk-daytime/quicktalk/template_900.mp4 \
  --audio ./assets/test.wav \
  --output ./outputs/quicktalk-bench.mp4 \
  --device cuda:0
```

输出会打印一段 JSON 指标，可用于对比不同 GPU、不同素材和不同模型版本的性能。

## 常见问题

### 端口被占用

给 `start_unified.sh` 指定新端口：

```bash
bash scripts/start_unified.sh --mock --api-port 8001 --web-port 5174
```

### 前端打开后连不上 API

先运行：

```bash
bash scripts/quickstart/status.sh
```

确认 API 端口在线。如果你改过 API 端口，需要确保 WebUI 启动时也拿到了相同端口。

### 模型没有生效

检查启动命令里是否同时指定了 `--backend` 和 `--model`。例如本地 QuickTalk 应该使用：

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

### 自定义 Avatar 不显示

确认 Avatar 目录在 `OPENTALKING_AVATARS_DIR` 下，并且目录中有合法的 `manifest.json` 和 `preview.png`。
