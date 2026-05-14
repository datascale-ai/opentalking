# Talking-head 模型

本页把 talking-head backend 解耦后的模型路径写成可执行流程：权重放哪里、
如何从国际和国内源下载、如何启动各个 backend，以及如何验证 OpenTalking 能成功创建会话。

OpenTalking 是编排层，模型执行按模型选择：

| 模型 | backend 状态 | 推荐首选路径 | 权重需求 |
|------|--------------|--------------|----------|
| `mock` | `mock` | 内置自测 | 无 |
| `wav2lip` | 兼容默认 `omnirt`；目标是 local-first | 轻量本地或单模型直连 backend；当前可直接跑通的是 OmniRT 兼容路径 | Wav2Lip + S3FD checkpoint |
| `musetalk` | `omnirt` | OmniRT 或后续本地 adapter | MuseTalk 1.5 权重 |
| `quicktalk` | `omnirt` | OmniRT `/v1/audio2video/quicktalk` | QuickTalk checkpoint + repair 参数 |
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
uv sync --extra dev --python 3.11
source .venv/bin/activate
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
uv pip install -U huggingface_hub
hf auth login  # 可选，私有或 gated 模型需要登录
```

如果服务器访问 Hugging Face 不稳定，可先配置镜像端点：

```bash title="终端"
export HF_ENDPOINT=https://hf-mirror.com
```

国内环境可优先使用 ModelScope 中已经同步的模型：

```bash title="终端"
uv pip install -U modelscope
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
uv sync --extra server --python 3.11
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
bash scripts/deploy_ascend_910b.sh
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

MuseTalk 当前走 OmniRT 兼容路径。OpenTalking 侧只负责模型注册、会话编排和连接
OmniRT；真正的 MuseTalk 推理与服务都在 OmniRT 内完成，不在 OpenTalking 仓库内直接
启动官方推理脚本。

上游入口：

- [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)
- [MuseTalk on Hugging Face](https://huggingface.co/TMElyralab/MuseTalk)
- [ModelScope 搜索 MuseTalk](https://modelscope.cn/models?name=MuseTalk)
- [魔乐社区搜索 MuseTalk](https://modelers.cn/models?name=MuseTalk)

### 1. 下载权重

MuseTalk 当前在线推理路径需要 UNet、VAE、Whisper、DWPose 和 face-parse 这几类权重。
推荐先建好目录，再分别下载到对应位置。

Hugging Face 主源：

- [TMElyralab/MuseTalk](https://huggingface.co/TMElyralab/MuseTalk)
- [stabilityai/sd-vae-ft-mse](https://huggingface.co/stabilityai/sd-vae-ft-mse)

```bash title="终端"
mkdir -p \
  "$OMNIRT_MODEL_ROOT/musetalk" \
  "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse" \
  "$OMNIRT_MODEL_ROOT/whisper" \
  "$OMNIRT_MODEL_ROOT/dwpose" \
  "$OMNIRT_MODEL_ROOT/face-parse-bisenet"

# MuseTalk UNet
hf download TMElyralab/MuseTalk \
  musetalk/pytorch_model.bin \
  musetalk/musetalk.json \
  --local-dir "$OMNIRT_MODEL_ROOT"

# VAE
hf download stabilityai/sd-vae-ft-mse \
  config.json \
  diffusion_pytorch_model.bin \
  --local-dir "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse"
```

`whisper/tiny.pt` 需要使用 OpenAI `openai-whisper` 官方 checkpoint，不要用 Hugging Face
的 `pytorch_model.bin` 改名替代。可直接下载到目标目录：

```bash title="终端"
curl -L \
  https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt \
  -o "$OMNIRT_MODEL_ROOT/whisper/tiny.pt"
```

下载 DWPose：

```bash title="终端"
hf download yzd-v/DWPose \
  dw-ll_ucoco_384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/dwpose"
```

下载 face-parse：

```bash title="终端"
uv pip install -U gdown
gdown --id 154JgKpzCPW82qINcVieuPH3fZ2e0P812 \
  -O "$OMNIRT_MODEL_ROOT/face-parse-bisenet/79999_iter.pth"
```

同目录下的 `resnet18-5c106cde.pth` 不是 OpenTalking quickstart 的硬性前置条件，当前
OmniRT 启动时如果缺失会自动下载；如果你想提前准备好，也可以手动放到同一目录：

```bash title="终端"
curl -L \
  https://download.pytorch.org/models/resnet18-5c106cde.pth \
  -o "$OMNIRT_MODEL_ROOT/face-parse-bisenet/resnet18-5c106cde.pth"
```

国内可选入口：

- [ModelScope 搜索 MuseTalk](https://modelscope.cn/models?name=MuseTalk)
- [ModelScope 搜索 sd-vae-ft-mse](https://modelscope.cn/models?name=sd-vae-ft-mse)
- [魔乐社区搜索 MuseTalk](https://modelers.cn/models?name=MuseTalk)
- [魔乐社区搜索 sd-vae-ft-mse](https://modelers.cn/models?name=sd-vae-ft-mse)

下载后先检查关键文件是否齐全：

```bash title="终端"
test -f "$OMNIRT_MODEL_ROOT/musetalk/pytorch_model.bin"
test -f "$OMNIRT_MODEL_ROOT/musetalk/musetalk.json"
test -f "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse/config.json"
test -f "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse/diffusion_pytorch_model.bin"
test -f "$OMNIRT_MODEL_ROOT/whisper/tiny.pt"
test -f "$OMNIRT_MODEL_ROOT/dwpose/dw-ll_ucoco_384.pth"
test -f "$OMNIRT_MODEL_ROOT/face-parse-bisenet/79999_iter.pth"
```

权重目录需要满足当前 OmniRT 适配代码的要求：

```text
$OMNIRT_MODEL_ROOT/
├── musetalk/
│   ├── pytorch_model.bin
│   └── musetalk.json
├── sd-vae-ft-mse/
│   ├── config.json
│   └── diffusion_pytorch_model.bin
├── whisper/
│   └── tiny.pt
├── dwpose/
│   └── dw-ll_ucoco_384.pth
└── face-parse-bisenet/
    └── 79999_iter.pth
```

其中：

- `whisper/tiny.pt` 必须是 `openai-whisper` 官方 checkpoint，不要用 Hugging Face 的
  `pytorch_model.bin` 改名替代。
- 官方 MuseTalk 仓会提到 `syncnet/latentsync_syncnet.pt`，但它主要用于训练、评估或
  lip-sync 打分，不属于当前 OpenTalking + OmniRT 实时推理链的必需项。

OmniRT 配置示例：

```yaml title="configs/default.yaml"
models:
  musetalk:
    backend: omnirt
```

2. 通过 OmniRT 启动 MuseTalk ：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda

# 如需改端口或指定 GPU
bash scripts/quickstart/start_omnirt_musetalk.sh \
  --device cuda \
  --port 9001 \
  --musetalk-port 8766
```

Ascend：

```bash title="终端"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/deploy_ascend_910b.sh

bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

3. 启动 OpenTalking

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="musetalk")'
```

期望状态：

```json
{"id":"musetalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```

和 Wav2Lip 的区别：

- Wav2Lip quickstart 直接用 `omnirt serve-avatar-ws` 起单层服务。
- MuseTalk quickstart 需要先起 MuseTalk WS backend，再由 OmniRT gateway 统一对外暴露
  `audio2video` 接口。
- MuseTalk runtime repo 由 OmniRT 自动管理，OpenTalking quickstart env 中不需要指定
  `OMNIRT_MUSETALK_REPO`。

## QuickTalk

QuickTalk 通过 OmniRT 作为 `audio2video` 模型服务部署，OpenTalking 只连接统一
`OMNIRT_ENDPOINT`，并按 `/v1/audio2video/quicktalk` 路径分发请求。OpenTalking 不直接
加载 QuickTalk 权重。

### 1. 下载 QuickTalk 权重

QuickTalk 自有模型文件位于 Hugging Face：

- [datascale-ai/quicktalk](https://huggingface.co/datascale-ai/quicktalk)

```bash title="终端"
mkdir -p "$OMNIRT_MODEL_ROOT/quicktalk"

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  --local-dir "$OMNIRT_MODEL_ROOT/quicktalk"
```

`repair.npy` 是 QuickTalk runtime 后处理阶段需要的修正参数，必须和 `quicktalk.pth`
放在同一个目录下。它不是独立神经网络 checkpoint。

如果部署机器不能直接访问 Hugging Face，也可以先在可联网机器或内部镜像准备好
QuickTalk 自有权重，再同步到同一个目录：

```bash title="终端"
export QUICKTALK_MODEL_BUNDLE=/path/to/quicktalk-model-bundle
mkdir -p "$OMNIRT_MODEL_ROOT/quicktalk"
rsync -a \
  "$QUICKTALK_MODEL_BUNDLE/quicktalk.pth" \
  "$QUICKTALK_MODEL_BUNDLE/repair.npy" \
  "$OMNIRT_MODEL_ROOT/quicktalk/"
```

### 2. 准备第三方依赖

QuickTalk runtime 还需要 HuBERT 与 InsightFace `buffalo_l` 依赖权重。它们不包含在
`datascale-ai/quicktalk` 中，需要按各自来源和许可单独下载，并放到同一个 QuickTalk
模型根目录下：

```text
$OMNIRT_MODEL_ROOT/quicktalk/
  quicktalk.pth
  repair.npy
  chinese-hubert-large/
    config.json
    preprocessor_config.json
    pytorch_model.bin
  auxiliary/models/buffalo_l/
    <InsightFace model files>
```

如果你的第三方资产来自 QuickTalk 原始资产目录，且文件位于 `checkpoints/` 下，可按下面
方式整理成 OpenTalking quickstart 使用的目录结构：

```bash title="终端"
export QUICKTALK_ASSET_SOURCE=/path/to/quicktalk_assets
mkdir -p "$OMNIRT_MODEL_ROOT/quicktalk"

rsync -a "$QUICKTALK_ASSET_SOURCE/checkpoints/repair.npy" \
  "$OMNIRT_MODEL_ROOT/quicktalk/repair.npy"
rsync -a "$QUICKTALK_ASSET_SOURCE/checkpoints/chinese-hubert-large/" \
  "$OMNIRT_MODEL_ROOT/quicktalk/chinese-hubert-large/"
rsync -a "$QUICKTALK_ASSET_SOURCE/checkpoints/auxiliary/" \
  "$OMNIRT_MODEL_ROOT/quicktalk/auxiliary/"
```

整理后先检查关键文件：

```bash title="终端"
test -f "$OMNIRT_MODEL_ROOT/quicktalk/quicktalk.pth"
test -f "$OMNIRT_MODEL_ROOT/quicktalk/repair.npy"
test -f "$OMNIRT_MODEL_ROOT/quicktalk/chinese-hubert-large/pytorch_model.bin"
test -f "$OMNIRT_MODEL_ROOT/quicktalk/auxiliary/models/buffalo_l/det_10g.onnx"
```

### 3. 准备 OmniRT

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
uv sync --extra server --extra quicktalk-cuda --python 3.11
```

`quicktalk-cuda` 中的 `torch` / `torchvision` 由 OmniRT `pyproject.toml` 固定到
PyTorch CUDA wheel 源；上面的镜像只用于普通 PyPI 包。

### 4. 启动 QuickTalk

QuickTalk 当前推荐 CUDA。默认画面参数由 helper 设置为：
`OMNIRT_QUICKTALK_MAX_LONG_EDGE=900`、`OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS=1`、
`OMNIRT_QUICKTALK_RESOLUTION=256`。

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_quicktalk.sh --device cuda
```

如需将主模型和 HuBERT 分配到不同 GPU：

```bash title="终端"
OMNIRT_QUICKTALK_DEVICE=cuda:0 \
OMNIRT_QUICKTALK_HUBERT_DEVICE=cuda:1 \
bash scripts/quickstart/start_omnirt_quicktalk.sh
```

### 5. 启动 OpenTalking

```bash title="终端"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

如果 OmniRT 在远端 GPU 机器，把 `--omnirt` 改成 `http://<gpu-server-ip>:9000`。

### 6. 验证

```bash title="终端"
curl -s http://127.0.0.1:9000/v1/audio2video/models | jq '.statuses[] | select(.id=="quicktalk")'
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```

期望 OpenTalking 返回：

```json
{"id":"quicktalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```

内置资产如果包含 `quicktalk/template_900.mp4` 和 `quicktalk/face_cache_v3_900.npz`，
OpenTalking 会在会话初始化时传给 OmniRT，减少首次对话的模板预处理耗时。

QuickTalk 实测性能（RTX 3090，OmniRT WebSocket 生成压测，720×900，25fps）：

| 模式 | 显存占用 | 生成吞吐 |
| --- | --- | --- |
| QuickTalk，主模型 `cuda:0` + HuBERT `cuda:1` | 约 3.8 GiB，总量拆分为主模型约 1.1 GiB、HuBERT 约 2.8 GiB | 约 35 fps |

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
