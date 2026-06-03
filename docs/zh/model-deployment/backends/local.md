# Local Adapter 部署

`local` backend 表示 OpenTalking 在自己的 Python 进程里 import 模型 adapter，并直接执行 audio-to-video 推理。它是单机验证最短路径。

## 基本流程

```bash title="终端"
cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
```

然后按模型页面准备权重，并通过统一脚本启动：

```bash title="终端"
bash scripts/start_unified.sh --backend local --model MODEL --api-port 8000 --web-port 5173
```

`MODEL` 可以是当前已实现 local adapter 的 talking-head 模型，例如 `wav2lip`、`quicktalk`、`musetalk`。

## 运行时行为

`start_unified.sh` 会设置：

```text
OPENTALKING_<MODEL>_BACKEND=local
OPENTALKING_DEFAULT_MODEL=<MODEL>
```

MuseTalk local 会额外执行 `scripts/quickstart/prepare_local_musetalk.sh`，用于检查模型权重、MuseTalk 源码、OpenMMLab 依赖和官方预处理 Python。

## 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.backend=="local")'
```

期望选中的模型返回：

```json
{"backend":"local","connected":true,"reason":"local_runtime"}
```

如果返回 `local_adapter_missing`，说明该模型没有注册本地 adapter，或者当前环境缺少对应依赖。

## 模型教程

- [QuickTalk Local](../quicktalk/local.md)
- [Wav2Lip Local](../wav2lip/local.md)
- [MuseTalk Local](../musetalk/local.md)
