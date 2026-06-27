# 命令行进阶参数

进阶参数主要用于控制启动脚本的模型后端、端口、绑定地址和环境文件。大多数情况下，你只需要使用 `scripts/start_unified.sh`；当你要接入远端推理、同时运行多个实例，或在服务器上开放 WebUI 时，再调整这些参数。

## 什么时候需要进阶参数

你可能会在这些情况下用到进阶参数：

- 本机已经有服务占用了默认端口。
- 需要把 WebUI 暴露给局域网内其他机器访问。
- 需要把某个模型切到本地、Mock、OmniRT 或直连 WebSocket 后端。
- 需要通过环境文件集中管理模型路径、Provider Key、镜像源和后端地址。

## Backend 选择参数

### `--mock`

`--mock` 是最轻量的启动方式：

```bash
bash scripts/start_unified.sh --mock
```

它会使用内置 Mock 后端，不加载模型权重，也不依赖 GPU。适合检查 WebUI、API、会话状态和基础音视频流程。

### `--backend`

`--backend` 用来指定某个模型使用的后端类型。

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

当前脚本接受的值包括：

- `mock`：不加载真实模型，适合流程验证。
- `local`：在 OpenTalking 进程内加载本地模型。
- `omnirt`：通过 OmniRT 访问独立推理服务。
- `direct_ws`：通过直连 WebSocket 方式对接后端。

### `--model`

`--model` 指定要覆盖后端的模型名称。

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

脚本会设置默认模型，并写入类似 `OPENTALKING_QUICKTALK_BACKEND=local` 的环境变量。模型名称需要和项目当前支持的模型标识保持一致。

## 服务端口参数

### `--api-port`

指定 OpenTalking API / unified 后端端口。

```bash
bash scripts/start_unified.sh --mock --api-port 8001
```

当默认端口被占用，或你需要同时跑多个实例时使用。

### `--web-port`

指定 WebUI dev server 端口。

```bash
bash scripts/start_unified.sh --mock --web-port 5174
```

如果你同时改了 API 和 WebUI 端口，建议两个参数一起传，避免前端仍连接旧 API。

### `--host`

指定 WebUI 绑定地址。

```bash
bash scripts/start_unified.sh --mock --host 0.0.0.0
```

本机调试一般使用默认值即可。需要从局域网访问 WebUI 时，可以绑定到 `0.0.0.0`，同时注意防火墙和网络访问控制。

## 远端推理参数

### `--omnirt`

当后端选择 `omnirt` 时，`--omnirt` 用来指定 OmniRT 服务地址。

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --omnirt http://127.0.0.1:9000
```

如果不传 `--omnirt`，需要提前设置 `OMNIRT_ENDPOINT`。

### `--env`

`--env` 用于加载 quickstart 环境文件。

```bash
cp scripts/quickstart/env.example .env.quickstart
bash scripts/start_unified.sh --env .env.quickstart --backend local --model quicktalk
```

环境文件适合放模型路径、TTS Provider Key、镜像源、默认端口等配置。建议不要把包含密钥的环境文件提交到仓库。

## 常见组合

### Mock 本地验证

```bash
bash scripts/start_unified.sh --mock
```

适合第一次验证安装、前端页面和基础交互。

### QuickTalk 本地模型

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

适合在本机 GPU 环境中验证 QuickTalk 推理效果。使用前需要确认模型权重和依赖已经准备好。

### OmniRT 远端模型

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000
```

适合把推理服务拆出去运行，让 OpenTalking 负责 WebUI、会话和业务编排。

### 自定义端口启动

```bash
bash scripts/start_unified.sh \
  --mock \
  --api-port 8001 \
  --web-port 5174
```

适合同一台机器上并行调试多个分支或多个配置。

## 常见问题

### `--backend omnirt` 提示缺少地址

传入 `--omnirt`，或提前设置：

```bash
export OMNIRT_ENDPOINT=http://127.0.0.1:9000
```

### WebUI 可以打开，但会话创建失败

优先检查 API 日志和模型后端是否在线。如果使用 OmniRT，确认 OmniRT 地址可访问，并且模型名与后端服务实际支持的模型一致。

### 局域网访问不了 WebUI

确认启动时使用了 `--host 0.0.0.0`，并检查服务器防火墙、安全组和 WebUI 端口是否开放。
