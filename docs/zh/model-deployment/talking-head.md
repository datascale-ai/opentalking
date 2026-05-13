# Talking-head 模型

本页把 talking-head backend 解耦后的模型路径写成可执行流程：权重放哪里、
如何从国际和国内源下载、如何启动各个 backend，以及如何验证 OpenTalking 能成功创建会话。

OpenTalking 是编排层，模型执行按模型选择：

| 模型 | backend 状态 | 推荐首选路径 | 权重需求 |
|------|--------------|--------------|----------|
| `mock` | `mock` | 内置自测 | 无 |
| `wav2lip` | 兼容默认 `omnirt`；目标是 local-first | 轻量本地或单模型直连 backend；当前可直接跑通的是 OmniRT 兼容路径 | Wav2Lip + S3FD checkpoint |
| `musetalk` | `omnirt` | OmniRT 或后续本地 adapter | MuseTalk 1.5 权重 |
| `quicktalk` | `local` | 本地 adapter | QuickTalk `hdModule` 资产包 |
| `flashtalk` | `omnirt` | OmniRT + CUDA 或 Ascend | SoulX-FlashTalk-14B + wav2vec2 |
| `flashhead` | `direct_ws` | 外部 FlashHead WebSocket 服务 | 由 FlashHead 服务自行管理 |

## 统一目录

建议把 OpenTalking、可选 backend 服务、模型、日志和运行时文件放在同一个父目录下。
只有 `backend: omnirt` 的模型需要 OmniRT。

```bash title="终端"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

mkdir -p "$DIGITAL_HUMAN_HOME" "$OMNIRT_MODEL_ROOT"
cd "$DIGITAL_HUMAN_HOME"
```

期望目录结构：

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
├── omnirt/                  # 可选，仅 backend: omnirt 需要
├── models/
│   ├── wav2lip/
│   ├── SoulX-FlashTalk-14B/
│   ├── chinese-wav2vec2-base/
│   └── quicktalk/
├── logs/
└── run/
```

先安装 OpenTalking：

```bash title="终端"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

至少在 `.env` 中配置 LLM/STT 凭据：

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

## 下载工具

国际网络环境可直接使用 Hugging Face：

```bash title="终端"
pip install -U "huggingface_hub[cli]"
hf auth login  # 可选，私有或 gated 模型需要登录
```

国内环境可优先使用 ModelScope 中已经同步的模型：

```bash title="终端"
pip install -U modelscope
modelscope login  # 可选
```

ModelScope 示例：

```bash title="终端"
# 快照下载。
modelscope download --model <namespace>/<model> --local_dir "$OMNIRT_MODEL_ROOT/<target>"

# CLI 版本差异时可用 Python fallback。
python - <<'PY'
from modelscope.hub.snapshot_download import snapshot_download
snapshot_download("<namespace>/<model>", local_dir="<target-dir>")
PY
```

魔乐社区（Modelers）也适合国内环境使用。若模型页提供 Git/LFS 或浏览器下载方式，按页面
说明下载，并保持下文约定的目标目录名一致。常用入口：

- [ModelScope 模型库](https://modelscope.cn/models)
- [魔乐社区模型库](https://modelers.cn/models)
- [Hugging Face 模型库](https://huggingface.co/models)

## Mock

`mock` 是最快的端到端路径。它不需要模型权重，可验证 API、前端、LLM、STT、TTS、事件
与 WebRTC。

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_mock.sh
```

打开 <http://127.0.0.1:5173>，选择 `demo-avatar`，再选择 `mock`。

验证：

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="mock")'
```

期望状态：

```json
{"id":"mock","backend":"mock","connected":true,"reason":"local_self_test"}
```

## Wav2Lip

Wav2Lip 是推荐的第一个真实模型：权重小、启动快、便于排错。产品默认部署方向应是本地
或单模型直连 backend，而不是强制依赖 OmniRT。当前版本为了兼容仍保留
`backend: omnirt` 作为可直接跑通路径，因为仓库内置的本地 Wav2Lip adapter 尚未补齐；
下述步骤是当前可运行的兼容路径。

### 1. 下载权重

Hugging Face 主源：

- [Pypa/wav2lip384](https://huggingface.co/Pypa/wav2lip384)
- [rippertnt/wav2lip](https://huggingface.co/rippertnt/wav2lip)

```bash title="终端"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"

hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"

hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

国内可选入口：

- [ModelScope 搜索 wav2lip384](https://modelscope.cn/models?name=wav2lip384)
- [ModelScope 搜索 s3fd wav2lip](https://modelscope.cn/models?name=s3fd%20wav2lip)
- [魔乐社区搜索 wav2lip384](https://modelers.cn/models?name=wav2lip384)

最终文件需要位于：

```text
$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth
$OMNIRT_MODEL_ROOT/wav2lip/s3fd.pth
```

### 2. 选择 backend

推荐目标部署：

```yaml title="configs/default.yaml"
models:
  wav2lip:
    backend: local      # 安装本地 adapter 后推荐
```

当前可运行兼容路径：

```yaml title="configs/default.yaml"
models:
  wav2lip:
    backend: omnirt
```

如果在未安装本地 adapter 前设置 `OPENTALKING_WAV2LIP_BACKEND=local`，`/models` 会按预期
返回 `connected=false` 与 `reason=local_adapter_missing`，不会静默回退 OmniRT。

### 3. 为兼容路径准备 OmniRT

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt
uv sync --extra server
```

### 4. 通过 OmniRT 启动 Wav2Lip

CUDA：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

Ascend：

```bash title="终端"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/quickstart/start_omnirt_wav2lip.sh --device npu
```

### 5. 启动 OpenTalking

```bash title="终端"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

验证：

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="wav2lip")'
```

当 OmniRT 已报告 Wav2Lip 时，期望：

```json
{"id":"wav2lip","backend":"omnirt","connected":true,"reason":"omnirt"}
```

前端选择 `singer`、`office-woman`、`laozi` 等 Wav2Lip avatar。

## MuseTalk 1.5

MuseTalk 已纳入可插拔模型配置；当前仓库提供 backend 框架，而不内置本地 MuseTalk
推理运行时。可选路径：

- OmniRT 已通过 `/v1/audio2video/musetalk` 提供 MuseTalk 时，使用 `backend: omnirt`。
- 你有独立 MuseTalk WebSocket 服务时，使用 `backend: direct_ws`。
- 只有在 `opentalking/models/musetalk/` 下实现本地 adapter 后，才使用 `backend: local`。

上游入口：

- [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)
- [MuseTalk on Hugging Face](https://huggingface.co/TMElyralab/MuseTalk)
- [ModelScope 搜索 MuseTalk](https://modelscope.cn/models?name=MuseTalk)
- [魔乐社区搜索 MuseTalk](https://modelers.cn/models?name=MuseTalk)

OmniRT 配置示例：

```yaml title="configs/default.yaml"
models:
  musetalk:
    backend: omnirt
```

指向已提供 MuseTalk 的 OmniRT：

```bash title="终端"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="musetalk")'
```

如需验证本地 adapter 缺失时的明确失败：

```bash title="终端"
OPENTALKING_MUSETALK_BACKEND=local bash scripts/quickstart/start_all.sh
```

期望失败状态：

```json
{"id":"musetalk","backend":"local","connected":false,"reason":"local_adapter_missing"}
```

## QuickTalk

QuickTalk 是本地 adapter 参考实现，不依赖 OmniRT。Adapter 从
`opentalking/models/quicktalk/` import，并在运行时加载 QuickTalk 资产包。

所需资产结构：

```text
$OMNIRT_MODEL_ROOT/quicktalk/hdModule/
└── checkpoints/
    ├── 256.onnx
    ├── repair.npy
    ├── chinese-hubert-large/
    └── auxiliary_min/ 或 auxiliary/
```

Avatar metadata 需要指向 QuickTalk 资产根目录与模板视频：

```json title="examples/avatars/quicktalk-demo/manifest.json"
{
  "id": "quicktalk-demo",
  "name": "QuickTalk Demo",
  "model_type": "quicktalk",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "metadata": {
    "asset_root": "/absolute/path/to/models/quicktalk/hdModule",
    "template_video": "/absolute/path/to/template.mp4"
  }
}
```

运行时环境：

```env title=".env"
OPENTALKING_QUICKTALK_ASSET_ROOT=/absolute/path/to/models/quicktalk/hdModule
OPENTALKING_QUICKTALK_TEMPLATE_VIDEO=/absolute/path/to/template.mp4
OPENTALKING_QUICKTALK_WORKER_CACHE=1
OPENTALKING_TORCH_DEVICE=cuda:0
```

启动：

```bash title="终端"
OPENTALKING_QUICKTALK_BACKEND=local bash scripts/quickstart/start_all.sh
```

验证：

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```

期望：

```json
{"id":"quicktalk","backend":"local","connected":true,"reason":"local_runtime"}
```

## FlashTalk

FlashTalk 是高质量路径，比 Wav2Lip 更重，推荐通过 OmniRT 部署在独立 GPU/NPU 主机上。

### 1. 下载权重

Hugging Face 主源：

- [Soul-AILab/SoulX-FlashTalk-14B](https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B)
- [TencentGameMate/chinese-wav2vec2-base](https://huggingface.co/TencentGameMate/chinese-wav2vec2-base)

```bash title="终端"
hf download Soul-AILab/SoulX-FlashTalk-14B \
  --local-dir "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B"

hf download TencentGameMate/chinese-wav2vec2-base \
  --local-dir "$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base"
```

国内可选入口：

- [ModelScope 搜索 SoulX-FlashTalk-14B](https://modelscope.cn/models?name=SoulX-FlashTalk-14B)
- [ModelScope 搜索 chinese-wav2vec2-base](https://modelscope.cn/models?name=chinese-wav2vec2-base)
- [魔乐社区搜索 SoulX-FlashTalk-14B](https://modelers.cn/models?name=SoulX-FlashTalk-14B)

CUDA helper 会用到可选源码 checkout：

```bash title="终端"
git clone https://github.com/Soul-AILab/SoulX-FlashTalk.git \
  "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk"
```

### 2. 通过 OmniRT 启动 FlashTalk

CUDA 单进程：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
```

Ascend 多进程：

```bash title="终端"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu --nproc 8
```

该 helper 会启动 FlashTalk worker service，将 OmniRT 指向该服务，并在 `9000` 端口暴露
OpenTalking 兼容的 audio2video 路由。

### 3. 启动 OpenTalking

```bash title="终端"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

验证：

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashtalk")'
```

期望：

```json
{"id":"flashtalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```

现有部署仍可使用 legacy WebSocket fallback：

```env title=".env"
OPENTALKING_FLASHTALK_WS_URL=ws://127.0.0.1:8765
```

新的单模型服务建议显式使用 `direct_ws`：

```yaml title="configs/default.yaml"
models:
  flashtalk:
    backend: direct_ws
    ws_url: ws://127.0.0.1:8765
```

## FlashHead

FlashHead 使用模型专属 WebSocket 协议，OpenTalking 将其视为 `backend: direct_ws`。
先单独启动 FlashHead 服务，再把 OpenTalking 指向其实时端点。

上游/搜索入口：

- [Hugging Face 搜索 SoulX FlashHead](https://huggingface.co/models?search=SoulX%20FlashHead)
- [ModelScope 搜索 FlashHead](https://modelscope.cn/models?name=FlashHead)
- [魔乐社区搜索 FlashHead](https://modelers.cn/models?name=FlashHead)

OpenTalking 配置：

```env title=".env"
OPENTALKING_FLASHHEAD_WS_URL=ws://<flashhead-host>:8766/v1/avatar/realtime
OPENTALKING_FLASHHEAD_BASE_URL=http://<flashhead-host>:8766
OPENTALKING_FLASHHEAD_MODEL=soulx-flashhead-1.3b
```

YAML：

```yaml title="configs/default.yaml"
models:
  flashhead:
    backend: direct_ws
```

启动 OpenTalking：

```bash title="终端"
bash scripts/quickstart/start_all.sh
```

验证：

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashhead")'
```

配置了 WebSocket URL 时，期望：

```json
{"id":"flashhead","backend":"direct_ws","connected":true,"reason":"direct_ws"}
```

前端使用 manifest 中 `model_type: "flashhead"` 的 avatar，例如 `anchor`。

## 通用验证

检查 OpenTalking：

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/models | jq
```

检查 OmniRT 承载的模型：

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
```

启动 UI：

```bash title="终端"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
open http://127.0.0.1:5173
```

## 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `reason=not_configured` | 端点或 WebSocket URL 为空。 | `omnirt` 模型配置 `OMNIRT_ENDPOINT`；`direct_ws` 模型配置 `OPENTALKING_<MODEL>_WS_URL`。 |
| `reason=omnirt_unavailable` | OmniRT 可达，但没有报告目标模型。 | 检查 `curl http://127.0.0.1:9000/v1/audio2video/models`、模型目录和 OmniRT 日志。 |
| `reason=local_adapter_missing` | 模型被配置为 `local`，但没有注册 adapter。 | 添加 `opentalking/models/<name>/adapter.py` 并注册，或切换到 `omnirt`/`direct_ws`。 |
| Wav2Lip helper 提示 checkpoint 缺失 | 文件不在 `$OMNIRT_MODEL_ROOT/wav2lip/`。 | 移动或重新下载 `wav2lip384.pth` 与 `s3fd.pth`。 |
| FlashTalk helper 提示目录缺失 | FlashTalk 或 wav2vec2 权重缺失。 | 确认 `$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B/` 与 `$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base/` 存在。 |
| 浏览器能看到模型但创建会话失败 | Avatar 的 `model_type` 与所选模型不匹配。 | 选择匹配模型的 avatar，或准备对应 avatar bundle。 |
