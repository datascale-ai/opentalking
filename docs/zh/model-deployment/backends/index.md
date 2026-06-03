# Backend 模式

OpenTalking 把会话编排、LLM、STT、TTS、Avatar 管理和 WebRTC 留在 OpenTalking 进程里，把 talking-head 推理放到可替换 backend。部署文档里最常用的是两种模式：`local` 和 `omnirt`。

| 模式 | 进程形态 | 适合场景 | 代价 |
|------|----------|----------|------|
| `local` | OpenTalking 进程内直接加载模型 adapter | 单机验证、最少组件、快速调试 | Python 依赖和模型显存与 OpenTalking 共享。 |
| `omnirt` | OpenTalking 连接独立 OmniRT 服务 | 服务隔离、多模型网关、GPU/NPU 专用运行时 | 需要单独维护 OmniRT checkout、`.venv`、端口和模型服务。 |

`mock` 用于无权重自测，`direct_ws` 用于模型自带独立 WebSocket 服务。它们仍在支持矩阵中保留，但本部署区优先整理 `local` 和 `omnirt`。

## 推荐工作目录

```bash title="终端"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"
export OPENTALKING_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

mkdir -p "$DIGITAL_HUMAN_HOME" "$OPENTALKING_MODEL_ROOT" "$DIGITAL_HUMAN_HOME/logs" "$DIGITAL_HUMAN_HOME/run"
```

仓库和模型建议分开：`opentalking/` 与 `omnirt/` 只放代码，模型权重放在 `$DIGITAL_HUMAN_HOME/models`。

## 国内镜像

quickstart 脚本会在未设置 `UV_DEFAULT_INDEX` / `UV_INDEX_URL` 时默认使用清华 PyPI 镜像。需要手动固定时可以显式设置：

```bash title="终端"
export UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
export PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy
```

镜像变量只影响 Python 包下载，不改变模型权重来源。
如果 `uv` 缓存和 `.venv` 不在同一个文件系统，建议保留 `UV_LINK_MODE=copy`，避免跨盘硬链接失败导致依赖安装状态异常。

## 通用验证

OpenTalking 启动后检查：

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/models | jq
```

OmniRT 模式额外检查：

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
```

## 下一步

- [Local Adapter](local.md)
- [OmniRT](omnirt.md)
- [Talking-head 模型](../talking-head/index.md)
- [支持矩阵](../support-matrix.md)
