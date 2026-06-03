# MuseTalk Local 单机部署

适用：你希望 OpenTalking 在本进程内加载 MuseTalk local adapter，并在创建会话前自动运行 MuseTalk 官方头像预处理。这个模式便于单机验证，但依赖比 Wav2Lip / QuickTalk 更重。

## 1. 准备 OpenTalking 环境

```bash title="终端"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"

# 网络较慢时先设置镜像。
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --python 3.11
uv pip install --python .venv/bin/python pip "setuptools<81" openmim
```

## 2. 准备 MuseTalk 权重

local 模式默认读取 `$OPENTALKING_MUSETALK_MODEL_ROOT`。推荐把 MuseTalk 相关权重整理到统一根目录，例如：

```bash title="终端"
export OPENTALKING_MUSETALK_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
mkdir -p "$OPENTALKING_MUSETALK_MODEL_ROOT"
```

OpenTalking 当前适配的是下面这个目录布局：

```text
$OPENTALKING_MUSETALK_MODEL_ROOT/
  musetalk/
    musetalk.json
    pytorch_model.bin
  sd-vae-ft-mse/
    config.json
    diffusion_pytorch_model.bin 或 diffusion_pytorch_model.safetensors
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

可从官方 MuseTalk 仓的 `download_weights.sh` 下载后整理。注意两处命名差异：

- 官方脚本的 VAE 目录常叫 `sd-vae`，这里需要整理或软链为 `sd-vae-ft-mse`。
- 官方脚本的 face parsing 目录常叫 `face-parse-bisent`，这里需要整理或软链为 `face-parse-bisenet`。

例如已有官方下载后的 `models/` 目录时：

```bash title="终端"
cd "$OPENTALKING_MUSETALK_MODEL_ROOT"
ln -s sd-vae sd-vae-ft-mse 2>/dev/null || true
ln -s face-parse-bisent face-parse-bisenet 2>/dev/null || true
```

Whisper 这里要求 OpenAI `openai-whisper` 的 `tiny.pt` 文件，不要把 Hugging Face `pytorch_model.bin` 直接改名顶替。

## 3. 准备 MuseTalk 官方源码和预处理依赖

OpenTalking local runtime 默认使用 OpenTalking 自己的 `.venv` 做推理和官方 MuseTalk 预处理。这样可以复用 `uv sync --extra models` 已安装的 torch / torchvision / cv2，避免再下载官方 `requirements.txt` 里的大体积 PyTorch。

```bash title="终端"
mkdir -p "$DIGITAL_HUMAN_HOME/model-repos"

git clone https://github.com/TMElyralab/MuseTalk.git "$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
# 如果服务器已经有官方 MuseTalk checkout，直接指向已有目录即可。

export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$OPENTALKING_HOME/.venv/bin/python"

"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m pip install json-tricks munkres pycocotools shapely terminaltables xtcocotools
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m pip install --no-build-isolation chumpy
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m mim install mmengine
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m pip install "mmcv-lite==2.0.1"
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m mim install "mmdet==3.1.0"
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m mim install "mmpose==1.1.0"
```

`start_unified.sh --backend local --model musetalk` 会再次调用 `scripts/quickstart/prepare_local_musetalk.sh` 做同样的依赖检查；上面的命令适合你想在启动前显式完成依赖安装。

## 4. 启动 OpenTalking

```bash title="终端"
export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$OPENTALKING_HOME/.venv/bin/python"
export OPENTALKING_MUSETALK_DEVICE=cuda:0
export OPENTALKING_TORCH_DEVICE=cuda:0
# 多卡机器可按需限制可见卡，避免误选不可用 GPU。
export CUDA_VISIBLE_DEVICES=0

cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model musetalk --api-port 8000 --web-port 5173
```

`start_unified.sh` 会调用 `scripts/quickstart/prepare_local_musetalk.sh` 检查依赖并补齐 OpenTalking `.venv` 中的 MuseTalk local runtime 包。如果当前头像目录没有 `prepared/prepared_info.json`，或其中不是 `source_preprocess=musetalk_official`，OpenTalking 会先运行 MuseTalk 官方预处理。

## 5. 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq ".statuses[] | select(.id==\"musetalk\")"
```

期望：

```json
{"id":"musetalk","backend":"local","connected":true,"reason":"local_runtime"}
```

打开 WebUI 后选择 MuseTalk 可用形象，发起一次实时对话。如果首个自定义形象没有预处理缓存，首次创建会话会比 Wav2Lip / QuickTalk 慢。
