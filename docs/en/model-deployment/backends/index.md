# Backend Modes

OpenTalking keeps orchestration, LLM, STT, TTS, avatar management, and WebRTC in the OpenTalking process. The talking-head runtime is selected through a backend. The deployment docs focus on `local` and `omnirt`.

| Mode | Process shape | Use it when | Cost |
|------|---------------|-------------|------|
| `local` | OpenTalking imports and runs the model adapter in-process. | Single-machine validation, minimal components, fast debugging. | Model dependencies and VRAM share the OpenTalking process. |
| `omnirt` | OpenTalking connects to an external OmniRT service. | Service isolation, model gateways, GPU/NPU-specific runtime. | Requires a separate OmniRT checkout, `.venv`, port, and model service. |

## Recommended Layout

```bash title="Terminal"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"
export OPENTALKING_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
```

## Package Mirrors

```bash title="Terminal"
export UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
export PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy
```

Keep `UV_LINK_MODE=copy` when the `uv` cache and `.venv` live on different filesystems; it avoids cross-device hardlink fallbacks leaving dependency installs in a bad state.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/models | jq
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
```

## Next Pages

- [Local Adapter](local.md)
- [OmniRT](omnirt.md)
- [Talking-Head Models](../talking-head/index.md)
- [Support Matrix](../support-matrix.md)
