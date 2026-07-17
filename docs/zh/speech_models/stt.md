# 语音识别模型

语音识别模型负责把麦克风或上传音频转成文本。纯文本 `speak` 请求不依赖 STT；只有用户通过语音输入时才需要配置本页能力。

## Provider 选项

| Provider / 模型 | 适用场景 | 必要配置 |
| --- | --- | --- |
| DashScope Paraformer realtime | 托管实时中文语音识别，适合默认麦克风链路 | `OPENTALKING_STT_DASHSCOPE_API_KEY` |
| [SenseVoiceSmall](stt/sensevoice.md) | 本地短句实时识别，适合私有化和 QuickTalk local 组合 | SenseVoiceSmall 权重和 FunASR 依赖 |

## DashScope Paraformer Realtime

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_STT_DASHSCOPE_MODEL=paraformer-realtime-v2
```

DashScope 部署中，LLM 与 STT 可以使用同一把实际 key，但必须分别写入 `OPENTALKING_LLM_API_KEY` 与 `OPENTALKING_STT_DASHSCOPE_API_KEY`。

## 本地 SenseVoiceSmall

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./avatar_models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu
```

下载权重：

```bash title="终端"
uv sync --extra dev --extra models --extra local-audio --python 3.11
python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model sensevoice-small
```

SenseVoiceSmall 走本地 FunASR adapter，支持上传音频和 WebSocket PCM 语音输入。短句场景下 CPU 通常可以满足实时交互。

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'
```

随后在前端麦克风流程中确认 session event stream 出现 STT 事件和 LLM 回复。
