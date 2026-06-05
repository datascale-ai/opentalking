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

OpenTalking local runtime 使用 OpenTalking 自己的 `.venv` 做实时推理，但官方 MuseTalk 头像预处理需要带 `mmcv._ext` 的 full OpenMMLab 环境。不要把预处理 Python 指向只装了 `mmcv-lite` 的主 `.venv`；推荐使用独立的 `$DIGITAL_HUMAN_HOME/runtimes/musetalk-preprocess/venv`。

```bash title="终端"
mkdir -p "$DIGITAL_HUMAN_HOME/model-repos"

git clone https://github.com/TMElyralab/MuseTalk.git "$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
# 如果服务器已经有官方 MuseTalk checkout，直接指向已有目录即可。

export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_ROOT="$DIGITAL_HUMAN_HOME/runtimes/musetalk-preprocess"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$OPENTALKING_MUSETALK_PREPROCESS_ROOT/venv/bin/python"

bash scripts/quickstart/prepare_local_musetalk.sh
```

`prepare_local_musetalk.sh` 会检查主 `.venv`、模型权重、MuseTalk 源码，以及独立预处理 venv。预处理 venv 会安装 `mmcv==2.0.1`、`mmdet==3.1.0`、`mmpose==1.1.0` 等官方预处理依赖；脚本会为常见 CUDA 11.8 环境自动补齐 `LD_LIBRARY_PATH`，确保 `mmcv._ext` 可加载。

`start_unified.sh --backend local --model musetalk` 会再次调用 `scripts/quickstart/prepare_local_musetalk.sh` 做同样的依赖检查；上面的命令适合你想在启动前显式完成依赖安装。

## 4. 启动 OpenTalking

```bash title="终端"
export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$DIGITAL_HUMAN_HOME/runtimes/musetalk-preprocess/venv/bin/python"
export OPENTALKING_MUSETALK_DEVICE=cuda:0
export OPENTALKING_TORCH_DEVICE=cuda:0
# 多卡机器可按需限制可见卡，避免误选不可用 GPU。
export CUDA_VISIBLE_DEVICES=0

cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model musetalk --api-port 8000 --web-port 5173
```

`start_unified.sh` 会调用 `scripts/quickstart/prepare_local_musetalk.sh` 检查依赖并补齐 OpenTalking `.venv` 中的 MuseTalk local runtime 包。如果当前头像目录没有 `prepared/prepared_info.json`，或其中不是 `source_preprocess=musetalk_official`，OpenTalking 会先运行 MuseTalk 官方预处理。

## 5. 启动或重启前端

上一步的 `scripts/start_unified.sh` 已经会启动 WebUI。若只需要重启前端，或后端已经在 `8000` 端口运行，另开终端执行：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

远程服务器部署时，把本地浏览器端口映射到服务器 `5173`，再打开 `http://127.0.0.1:5173`。

## 6. 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | python3 -m json.tool
```

期望：

```json
{"id":"musetalk","backend":"local","connected":true,"reason":"local_runtime"}
```

打开 WebUI 后选择 MuseTalk 可用形象，发起一次实时对话。如果该形象没有 `prepared/prepared_info.json`，首次创建会话会先运行官方预处理，通常会明显慢于 Wav2Lip / QuickTalk；后续命中缓存后会快很多。若遇到 `No module named 'mmcv._ext'`，说明 `OPENTALKING_MUSETALK_PREPROCESS_PYTHON` 指向了错误环境或 CUDA library path 不完整，重新执行第 3 节的准备脚本。
