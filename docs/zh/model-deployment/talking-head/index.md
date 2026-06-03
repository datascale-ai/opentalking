# 数字人模型部署

本页是 talking-head backend 的选型总览。OpenTalking 负责会话编排、TTS、事件和 WebRTC；
模型权重加载、GPU/NPU 调度和推理吞吐由所选 backend 承担。

## 推荐路径

| 模型 | backend | 推荐场景 | 证据等级 | 详情 |
|------|---------|----------|----------|------|
| `mock` | `mock` | 首次运行、CI、排查 API/WebRTC | 已内置，已验证 | [Mock](../mock.md) |
| `wav2lip` | `local` / `omnirt` | 第一个真实唇形模型 | local adapter 已内置；OmniRT 路径已验证 | [Local](../wav2lip/local.md) / [OmniRT](../wav2lip/omnirt.md) |
| `musetalk` | `local` / `omnirt` / `direct_ws` | 使用进程内启动或外部服务获得 MuseTalk 质量 | local adapter 已内置；OmniRT/direct_ws 路径已文档化 | [Local](../musetalk/local.md) / [OmniRT](../musetalk/omnirt.md) |
| `quicktalk` | `local` / `omnirt` | 本地实时 adapter 或 OmniRT 服务化部署 | local 已内置；OmniRT 路径已接入 | [Local](../quicktalk/local.md) / [OmniRT](../quicktalk/omnirt.md) |
| `fasterliveportrait` | `omnirt` | 单卡实时音频驱动头像并贴回原始资产图 | 已文档化 | [FasterLivePortrait](../fasterliveportrait.md) |
| `flashtalk` | `omnirt` | 高质量私有化、GPU/NPU 重模型 | OmniRT/Ascend 路径已验证 | [FlashTalk](../flashtalk.md) |
| `flashhead` | `direct_ws` | 已有独立 FlashHead 服务 | 已文档化 | [FlashHead](../flashhead.md) |

## Backend 行为

| Backend | OpenTalking 期望什么 | 典型模型 |
|---------|----------------------|----------|
| `mock` | 无外部 runtime，始终可用。 | `mock` |
| `local` | 本进程可 import adapter，依赖满足。 | `wav2lip`、`quicktalk`、`musetalk` |
| `direct_ws` | 模型服务提供专属 WebSocket URL。 | `flashhead`、自定义单模型服务 |
| `omnirt` | OmniRT 暴露 `/v1/audio2video/{model}`。 | `wav2lip`、`musetalk`、`quicktalk`、`fasterliveportrait`、`flashtalk` |

## 通用准备

```bash title="终端"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OMNIRT_HOME="${OMNIRT_HOME:-$DIGITAL_HUMAN_HOME/omnirt}"
export FASTERLIVEPORTRAIT_HOME="${FASTERLIVEPORTRAIT_HOME:-$DIGITAL_HUMAN_HOME/FasterLivePortrait}"

mkdir -p "$DIGITAL_HUMAN_HOME" "$OMNIRT_MODEL_ROOT"
cd "$DIGITAL_HUMAN_HOME"
```

推荐目录：

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
├── omnirt/                  # 可选，仅 backend: omnirt 需要
├── models/
│   ├── wav2lip/
│   ├── SoulX-FlashTalk-14B/
│   ├── chinese-wav2vec2-base/
│   ├── quicktalk/
│   └── FasterLivePortrait/
├── logs/
└── run/
```

下载工具：

```bash title="终端"
uv pip install -U "huggingface_hub[cli]" modelscope
```

国内环境优先查：

- [ModelScope 模型库](https://modelscope.cn/models)
- [魔乐社区模型库](https://modelers.cn/models)
- [Hugging Face 模型库](https://huggingface.co/models)

## 通用验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/models | jq
```

OmniRT 承载的模型可额外检查：

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
```

## 常见状态

| 状态 | 含义 | 处理 |
|------|------|------|
| `connected=true` | 当前 backend 已可用于会话。 | 进入浏览器选择匹配 avatar 和模型。 |
| `reason=not_configured` | 端点或 WebSocket URL 为空。 | 配置 `OMNIRT_ENDPOINT` 或模型专属 `WS_URL`。 |
| `reason=omnirt_unavailable` | OmniRT 可达性或模型注册异常。 | 查 OmniRT `/v1/audio2video/models`、模型列表和日志。 |
| `reason=local_adapter_missing` | 配置为 `local`，但未注册本地 adapter。 | 切换 backend 或补本地 adapter。 |
