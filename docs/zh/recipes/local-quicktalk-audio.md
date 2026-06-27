# 本地 STT/TTS + QuickTalk

本页描述一条面向私有化验证的单机路线：

- STT：本地 `SenseVoiceSmall`，默认 CPU。
- TTS：本地 `Fun-CosyVoice3-0.5B-2512`，通过 `local_cosyvoice` service 输出音频。
- Video：本地 `QuickTalk`，默认 CUDA。
- LLM：仍通过 OpenAI-compatible endpoint 配置；如果你已有本地 LLM 服务，也可以把 `OPENTALKING_LLM_BASE_URL` 指向本地服务。

这条路线保持 OpenTalking 现有 `/sessions/*`、`/tts/preview` 和 session runner 协议不变。前端只是在启动会话前选择本地或 API provider；选择 API provider 且缺少对应 key 时会在启动前报错，不会自动 fallback 到本地或云端。

## 硬件建议

| 组件 | 默认放置 | 建议 |
|------|----------|------|
| SenseVoiceSmall | CPU | 短句通常够用，可减少显存占用。 |
| Fun-CosyVoice3-0.5B-2512 | `cuda:0` | 建议 12GB 显存；8GB 环境优先改用 API TTS。 |
| QuickTalk | `cuda:0` | 与本地 TTS 共卡时要关注显存峰值和首轮预热。 |

## 安装依赖

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra local-audio --extra quicktalk-cuda --python 3.11
source .venv/bin/activate
```

OpenTalking 主 venv 负责 API、SenseVoice 和 QuickTalk，并保留项目级
`transformers>=4.57,<6` 依赖。不要把 CosyVoice runtime 安装进这个 venv。

## 下载本地音频模型

权重不要提交到 git。默认下载脚本会使用 ModelScope；如需 Hugging Face 可设置镜像。

```bash title="终端"
python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model sensevoice-small \
  --model fun-cosyvoice3-0.5b-2512
```

期望目录：

```text
models/local-audio/
  iic__SenseVoiceSmall/
  FunAudioLLM__Fun-CosyVoice3-0.5B-2512/
```

## 准备 QuickTalk 权重

QuickTalk 的模型权重、HuBERT 和 InsightFace 依赖按 [QuickTalk Local 部署](../avatar_models/deployment/quicktalk-local.md) 文档放到：

```text
models/quicktalk/checkpoints/
```

关键配置是 `OPENTALKING_QUICKTALK_ASSET_ROOT` 指向包含 `checkpoints/` 的目录。

## 准备 CosyVoice runtime

`local_cosyvoice` 推荐通过独立 Python service 接入。运行时代码不提交到 git，可放在模型目录下：

```bash title="终端"
mkdir -p ./avatar_models/local-audio/runtime
git clone https://github.com/FunAudioLLM/CosyVoice.git ./avatar_models/local-audio/runtime/CosyVoice
cd ./avatar_models/local-audio/runtime/CosyVoice
git submodule update --init --recursive
```

runtime 准备好后，创建 CosyVoice 专用 sidecar venv：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

这个 sidecar venv 只用于 `scripts/local_cosyvoice_service.py` 和 CosyVoice
runtime，内部固定 `transformers==4.51.3`，与 OpenTalking 主 `.venv` 隔离。

## `.env` 示例

```env title=".env"
# LLM：仍是独立模块。可指向百炼、OpenAI、vLLM、Ollama 或本地 OpenAI-compatible 服务。
OPENTALKING_LLM_PROVIDER=openai_compatible
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=<llm-key>
OPENTALKING_LLM_MODEL=qwen-flash

# STT：本地 SenseVoiceSmall
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./avatar_models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu

# TTS：本地 CosyVoice3
OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=local_cosyvoice,dashscope,edge
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR=./avatar_models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR=./avatar_models/local-audio/runtime/CosyVoice
OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize
OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE=cuda:0
OPENTALKING_COSYVOICE_VENV_DIR=./.venv-cosyvoice

# Video：QuickTalk local
OPENTALKING_DEFAULT_MODEL=quicktalk
OPENTALKING_QUICKTALK_BACKEND=local
OPENTALKING_QUICKTALK_ASSET_ROOT=./avatar_models/quicktalk
OPENTALKING_QUICKTALK_WORKER_CACHE=1
OPENTALKING_TORCH_DEVICE=cuda:0
```

如果前端允许用户切换到 API STT/TTS，则 API key 仍需要显式配置到 provider-specific 变量：

```env title=".env"
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-stt-key>
OPENTALKING_TTS_DASHSCOPE_API_KEY=<dashscope-tts-key>
```

## 启动顺序

先启动本地 TTS service：

```bash title="终端"
bash scripts/quickstart/start_local_cosyvoice.sh --port 19090
```

再启动 OpenTalking：

```bash title="终端"
bash scripts/start_unified.sh --backend local --model quicktalk
```

需要指定端口时：

```bash title="终端"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:19090/health
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/runtime/status
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```

期望状态：

- `stt_provider` 为 `sensevoice`。
- `tts_provider` 为 `local_cosyvoice`。
- `quicktalk_backend` 为 `local`。
- `/models` 中 `quicktalk.connected=true`，`reason=local_runtime`。

前端中选择 `Local SenseVoiceSmall`、`Local CosyVoice3-0.5B-2512` 和 QuickTalk 形象后，再测试：

1. 文本输入：`LLM -> local_cosyvoice -> QuickTalk -> WebRTC`。
2. 麦克风输入：`SenseVoiceSmall -> LLM -> local_cosyvoice -> QuickTalk -> WebRTC`。
3. `/tts/preview`：确认本地音色和复刻音色能播放。

## 注意事项

- `*_DEFAULT_PROVIDER` 只是默认选中项，不是失败 fallback。
- LLM、STT、TTS 的 key 相互独立；`DASHSCOPE_API_KEY` 不会自动作用到任何模块。
- CosyVoice3 service 返回音频流，但首包延迟仍取决于模型推理和预热状态。
- 8GB 显存环境如果卡顿或 OOM，优先保留 `SenseVoiceSmall CPU + QuickTalk local`，TTS 改用 DashScope 或 Edge。
- 权重、runtime checkout、avatar cache 和运行日志都属于部署产物，不应提交到代码仓。
