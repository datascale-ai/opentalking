# 运行方法

## QuickTalk 本地 adapter

仓库提供 `apps/cli/quicktalk_bench.py`，用于直接测 QuickTalk 本地 adapter 的加载、首帧、
渲染和 mux 时间。

```bash title="终端"
source .venv/bin/activate
python apps/cli/quicktalk_bench.py \
  --asset-root /path/to/quicktalk/assets \
  --template-video /path/to/template.mp4 \
  --audio /path/to/input.wav \
  --output outputs/benchmarks/quicktalk-output.mp4 \
  --device cuda:0
```

输出 JSON 包含：

- `init_seconds`
- `audio_feature_seconds`
- `first_frame_seconds`
- `render_seconds`
- `render_fps`
- `mux_seconds`

## OpenTalking 端到端链路

端到端测试应先固定模型、TTS provider 和输入音频，再记录浏览器、API 与 Worker 日志。

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/models | jq
```

建议记录：

- OpenTalking commit、配置文件、`.env` 中非密钥配置。
- 硬件与驱动版本。
- 选中的 `avatar_id`、`model`、`backend`。
- 输入音频时长、采样率和文本内容。
- 首 token、TTS 首包、avatar 首帧、浏览器首帧和音画同步结果。

## 外部模型服务

OmniRT、FlashHead direct WebSocket 或其它模型服务的推理数据应使用对应服务的 benchmark
工具生成。OpenTalking 文档只引用结果，并记录 OpenTalking 侧的调用、队列和播放表现。
