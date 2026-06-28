# F5-TTS 本地部署

F5-TTS 通过 OpenTalking 的 `local_f5_tts` provider 接入，适合本地音色克隆、短句实时回复和离线视频配音。当前实现采用同机 HTTP sidecar：OpenTalking 主进程只负责调度，F5-TTS 运行在独立 venv 中，避免依赖和 CUDA 包冲突。

## 适用场景

- 需要本地音色克隆，不希望调用托管 TTS API。
- 已有 3-15 秒参考音频和对应文本，希望复刻说话人音色。
- 需要把 F5-TTS runtime 与 OpenTalking 主进程隔离。

## 权重准备

推荐把权重放到统一的本地音频模型目录，例如 `$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT`：

```bash title="终端"
cd "$OPENTALKING_HOME"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="${OPENTALKING_LOCAL_AUDIO_MODEL_ROOT:-$OPENTALKING_HOME/models/local-audio}"

python scripts/download_local_audio_models.py \
  --root "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT" \
  --model f5-tts-v1-base
```

脚本会把 `SWivid/F5-TTS` 的 `F5TTS_v1_Base/model_1250000.safetensors` 映射到：

```text
$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/SWivid__F5-TTS__F5TTS_v1_Base/model_1250000.safetensors
```

准备 runtime 和独立 venv：

```bash title="终端"
mkdir -p "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime"
cd "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime"

if [ ! -d F5-TTS/.git ]; then
  git clone https://github.com/SWivid/F5-TTS.git F5-TTS
fi

python3 -m venv --system-site-packages "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system"
. "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system/bin/activate"
pip install -U pip wheel setuptools
pip install --no-deps -e "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/F5-TTS"
pip install fastapi "uvicorn[standard]" soundfile cached_path hydra-core ema_pytorch vocos x_transformers transformers_stream_generator rjieba pypinyin tomli bitsandbytes pydub torchcodec torchdiffeq unidecode wandb
```

## 配置项

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_f5_tts
OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL=http://127.0.0.1:19095/synthesize
OPENTALKING_LOCAL_AUDIO_MODEL_ROOT=./models/local-audio
OPENTALKING_TTS_LOCAL_F5_TTS_RUNTIME_DIR=./models/local-audio/runtime/F5-TTS
OPENTALKING_TTS_LOCAL_F5_TTS_DEVICE=cuda
```

## 音色克隆

`local_f5_tts` 请求必须带参考音频。可以通过 API 上传 clone voice，也可以手工准备目录：

```text
$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/voices/clones/my-f5-voice/
  prompt.wav
  prompt.txt
  meta.json
```

`meta.json` 示例：

```json
{"provider":"local_f5_tts"}
```

上传后 `/api/voices?provider=local_f5_tts` 会返回可选 voice id；TTS preview、实时对话和视频生成都可以使用这个 voice。

## 启动命令

先启动 F5-TTS sidecar，再启动 OpenTalking：

```bash title="终端"
cd "$OPENTALKING_HOME"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="${OPENTALKING_LOCAL_AUDIO_MODEL_ROOT:-$OPENTALKING_HOME/models/local-audio}"
export OPENTALKING_F5_TTS_VENV_DIR="$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system"
bash scripts/quickstart/start_local_f5_tts.sh --port 19095

export OPENTALKING_TTS_DEFAULT_PROVIDER=local_f5_tts
export OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL=http://127.0.0.1:19095/synthesize
python -m apps.api.main
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:19095/health
curl -fsS http://127.0.0.1:8000/health
```

TTS preview 应使用 `local_f5_tts` provider 和一个带 `prompt.wav` 的 clone voice。生成结果可以保存成 WAV 后用 ASR 或人工听检确认文本和音色。

## 实测记录

| 项目 | 命令 / 接口 | 目标 | 实测 |
|------|-------------|------|------|
| TTS preview | `/tts/preview` + SenseVoiceSmall ASR | 可播放 WAV，文本正确 | 通过：试听接口返回 16 kHz mono WAV；SenseVoiceSmall ASR 识别文本与目标文本一致。 |
| 实时对话 | local mode dialogue / warm TTS | RTF < 1.0 | 通过：warm RTF 0.278（3.31s 音频，0.918s 合成）；历史复测 0.386/0.518，均低于 1 |
| 离线视频 | video generation API / CLI | 生成成功，音频驱动正常 | 通过：QuickTalk + F5 clone voice 可生成 MP4；ffprobe 显示 H.264 视频和 16 kHz mono AAC 音频。 |

## 常见错误

| 现象 | 处理 |
|------|------|
| `Missing F5-TTS checkpoint` | 确认 `model_1250000.safetensors` 位于 `SWivid__F5-TTS__F5TTS_v1_Base` 目录。 |
| `requires prompt_audio` | 选择 clone voice，或设置 `OPENTALKING_TTS_LOCAL_F5_TTS_PROMPT_AUDIO`。 |
| 依赖冲突 | 不要用 OpenTalking 主 `.venv` 启动 sidecar；建议使用 `$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system` 这样的独立 venv，并复用宿主机已有 PyTorch/CUDA 环境。 |
| 首次请求慢 | 设置 `OPENTALKING_TTS_LOCAL_F5_TTS_PRELOAD=1` 并在服务启动后先做一次短句预热。 |
| QuickTalk v3 reshape 报错 | 使用当前 TorchScript 导出模型生成视频时保持 `OPENTALKING_QUICKTALK_RESOLUTION=256`；160/128 分辨率会让模型内部特征尺寸不匹配。 |
