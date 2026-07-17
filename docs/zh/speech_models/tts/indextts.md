# IndexTTS 本地部署

IndexTTS 通过 OpenTalking 的 `indextts` provider 接入，适合可控配音、情绪控制和复刻音色。本文覆盖同机 HTTP sidecar 方式。

## 适用场景

- 需要比默认 Edge TTS 更强的音色控制。
- 希望把 IndexTTS runtime 与 OpenTalking 主进程隔离。
- 需要本地部署而不是托管 TTS API。

## 部署根目录

后续命令默认在同一个终端中执行。先进入 OpenTalking 仓库目录，并只在这里设置一次
部署根目录：

```bash title="终端"
cd /path/to/digital_human/opentalking
export OPENTALKING_HOME="$(pwd)"
case "${DIGITAL_HUMAN_HOME:-}" in
  ""|/path/to/digital_human) export DIGITAL_HUMAN_HOME="$(cd "$OPENTALKING_HOME/.." && pwd)" ;;
esac
export OPENTALKING_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OPENTALKING_MODEL_REPO_ROOT="$DIGITAL_HUMAN_HOME/model-repos"
export OPENTALKING_RUNTIME_ROOT="$DIGITAL_HUMAN_HOME/runtimes"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="$OPENTALKING_MODEL_ROOT/local-audio"
export OPENTALKING_TTS_LOCAL_INDEXTTS_RUNTIME_DIR="$OPENTALKING_MODEL_REPO_ROOT/index-tts"
export OPENTALKING_INDEXTTS_VENV_DIR="$OPENTALKING_RUNTIME_ROOT/index-tts/venv"
```

## 权重准备

推荐使用统一目录：权重放在 `$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT`，IndexTTS
源码 checkout 放在 `$OPENTALKING_MODEL_REPO_ROOT`，sidecar venv 放在
`$OPENTALKING_RUNTIME_ROOT`。

```bash title="终端"
cd "$OPENTALKING_HOME"
mkdir -p "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# HF Xet/CAS 链路在部分网络环境下可能反复 SSL resume，优先使用普通 HTTP 下载。
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
uv sync --extra dev --extra models --extra local-audio --extra quicktalk-cuda --python 3.11

python scripts/download_local_audio_models.py \
  --root "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT" \
  --model indextts2 \
  --model indextts2-w2v-bert \
  --model indextts2-maskgct \
  --model indextts2-campplus \
  --model indextts2-bigvgan
```

准备 runtime：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME"
mkdir -p "$OPENTALKING_MODEL_REPO_ROOT" "$OPENTALKING_RUNTIME_ROOT/index-tts"
# 可选：GitHub 访问慢时，可临时启用代理前缀。
# export GITHUB_PROXY_PREFIX=https://gh-proxy.com/
# 可选：PyPI 访问慢时，可临时启用清华镜像。
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-$UV_DEFAULT_INDEX}"
# 避免 ~/.cache/uv 或 ~/.cache/pip 曾被 root 写入后导致普通用户安装失败。
export UV_CACHE_DIR="${UV_CACHE_DIR:-$OPENTALKING_RUNTIME_ROOT/.uv-cache}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$OPENTALKING_RUNTIME_ROOT/.pip-cache}"
if [ ! -d "$OPENTALKING_MODEL_REPO_ROOT/index-tts/.git" ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone "${GITHUB_PROXY_PREFIX:-}https://github.com/index-tts/index-tts.git" "$OPENTALKING_MODEL_REPO_ROOT/index-tts"
fi

mkdir -p "$UV_CACHE_DIR" "$PIP_CACHE_DIR"
uv venv --seed --python 3.11 "$OPENTALKING_RUNTIME_ROOT/index-tts/venv"
"$OPENTALKING_RUNTIME_ROOT/index-tts/venv/bin/python" -m pip install -U pip wheel setuptools
cd "$OPENTALKING_MODEL_REPO_ROOT/index-tts"
"$OPENTALKING_RUNTIME_ROOT/index-tts/venv/bin/python" -m pip install -e .
cd "$DIGITAL_HUMAN_HOME"
"$OPENTALKING_RUNTIME_ROOT/index-tts/venv/bin/python" -m pip install fastapi "uvicorn[standard]" soundfile
```

不要把 `index-tts` 安装进 OpenTalking 主 `.venv`；OpenTalking 主进程通过 HTTP
调用 sidecar。

## 配置项

```env title=".env"
DIGITAL_HUMAN_HOME=/path/to/digital_human
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=local
OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL=http://127.0.0.1:19092/synthesize
OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE=cuda:0
OPENTALKING_TTS_VOICE=indextts-xiaoxiao-cn
```

只需要把 `DIGITAL_HUMAN_HOME` 改成真实部署根目录；其它模型、runtime 和 venv
路径在下面的启动命令中从它推导，避免 `.env` 里残留错误绝对路径。

如果由 OmniRT 承载 IndexTTS runtime，OpenTalking 仍然使用 `provider=indextts`，
只需要把 backend 切到 `omnirt`，并指向常驻 OmniRT 服务。OmniRT 侧负责模型加载、
分窗流式和 token-window streaming：

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=omnirt
OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL=http://127.0.0.1:9012/v1/text2audio/indextts
OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING_MODE=token_window
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE=40
```

## 启动命令

先启动 IndexTTS sidecar，再启动 OpenTalking + QuickTalk。sidecar 的 HTTP 路径和端口
必须与 `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL` 匹配。

```bash title="终端"
cd "$OPENTALKING_HOME"

bash scripts/quickstart/start_local_indextts.sh --port 19092 --device cuda:0

export OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
export OPENTALKING_TTS_INDEXTTS_BACKEND=local
export OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL=http://127.0.0.1:19092/synthesize
export OPENTALKING_TTS_VOICE=indextts-xiaoxiao-cn

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$OPENTALKING_MODEL_ROOT/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5283
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:19092/health
curl -fsS http://127.0.0.1:8210/health
curl -fsS http://127.0.0.1:8210/runtime/status | jq '.tts_providers.indextts.service_url_set'
```

状态中应看到 `true`。创建 `quicktalk` 会话后调用 `/speak` 验证 TTS provider
是否返回音频并驱动 QuickTalk。

## 关闭服务

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/stop_all.sh --api-port 8210 --web-port 5283
```

这个命令会关闭 OpenTalking API、WebUI，以及通过上面命令写入 pid 文件的
IndexTTS sidecar。

## 常见错误

| 现象 | 处理 |
|------|------|
| `service_url_set=false` | 确认使用 `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL`，不是 `OPENTALKING_TTS_INDEXTTS_SERVICE_URL`。 |
| sidecar 接口不匹配 | 检查 sidecar 端口和路径是否与 `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL` 一致；默认端口为 `19092`。 |
| 下载时反复出现 `cas-bridge.xethub.hf.co` 或 SSL resume | 保留 `HF_HUB_DISABLE_XET=1` 后重新运行同一条下载命令；脚本会复用已完整下载的模型目录。必要时临时改用 `HF_ENDPOINT=https://huggingface.co`。 |
| 下载缺文件 | 重新运行下载脚本，确认五个 `indextts2*` 模型目录都存在。 |
| QuickTalk 报 `onnxruntime` 没有 `InferenceSession` | 重新运行 `uv sync --extra dev --extra models --extra local-audio --extra quicktalk-cuda --python 3.11`；CPU 环境把 `quicktalk-cuda` 换成 `quicktalk-cpu`。 |
| 依赖冲突 | 将 IndexTTS runtime 保持在独立 venv 中，不要安装进 OpenTalking 主 `.venv`。 |
