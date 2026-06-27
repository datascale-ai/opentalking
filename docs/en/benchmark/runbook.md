# Runbook

## QuickTalk Local Adapter

The repository includes `apps/cli/quicktalk_bench.py` for measuring QuickTalk local adapter
load time, first frame, render throughput, and mux time.

```bash title="Terminal"
source .venv/bin/activate
python apps/cli/quicktalk_bench.py \
  --asset-root /path/to/quicktalk/assets \
  --template-video /path/to/template.mp4 \
  --audio /path/to/input.wav \
  --output outputs/benchmarks/quicktalk-output.mp4 \
  --device cuda:0
```

The JSON output includes:

- `init_seconds`
- `audio_feature_seconds`
- `first_frame_seconds`
- `render_seconds`
- `render_fps`
- `mux_seconds`

## OpenTalking End-to-End Path

End-to-end testing should pin the model, TTS provider, and input audio before collecting
browser, API, and Worker logs.

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/models | jq
```

Record:

- OpenTalking commit, config file, and non-secret `.env` settings.
- Hardware and driver versions.
- Selected `avatar_id`, `model`, and `backend`.
- Input audio duration, sample rate, and prompt text.
- First token, TTS first packet, avatar first frame, browser first frame, and A/V sync.

## External Model Services

OmniRT, FlashHead direct WebSocket, or other model services should be benchmarked with
their own tools. OpenTalking documentation should reference those results and record only
the OpenTalking-side call, queue, and playback behavior.
