# Platform Notes

This page explains the recommended ways to run OpenTalking on different system environments. For first-time use, start with Mock mode in [Quick Start](index.md). When you need real digital-human rendering models, choose the appropriate path according to your GPU/NPU environment.

## Support Matrix

| Platform | Recommended Use | Available Paths | Notes |
| --- | --- | --- | --- |
| macOS | Docs, frontend, API, Mock validation | `mock` | Good for quick trials, not recommended as a real model inference environment. |
| Linux + CUDA | Real model validation and deployment | `mock`, `quicktalk`, `wav2lip`, `musetalk`, `omnirt` | Primary recommended environment. |
| Linux + Ascend NPU | Private deployment and NPU evaluation | `mock`, selected OmniRT / FlashTalk paths | Requires CANN, driver, and `torch_npu`. |

## macOS Notes

### Suitable for mock / frontend / API development

macOS is suitable for Mock mode, WebUI development, API debugging, and documentation work. You can use it to validate LLM, TTS, subtitle events, and WebRTC playback.

```bash
brew install python@3.11 node ffmpeg
uv sync --extra dev --python 3.11
```

### Not suitable for real digital-human models

QuickTalk, MuseTalk, FlashTalk, and similar models mainly target CUDA GPUs or dedicated inference services. Even if some Python dependencies can be installed on macOS, it is not recommended as the real video-generation path. Deploy models on a Linux GPU machine and connect OpenTalking to the remote inference service instead.

### ffmpeg Installation

OpenTalking uses FFmpeg for TTS decoding, audio processing, and video processing. Install it on macOS with:

```bash
brew install ffmpeg
ffmpeg -version
```

## Linux + CUDA Notes

### Recommended for real models

Linux with NVIDIA GPU is the recommended environment for real model validation. After Mock mode works, continue with QuickTalk, Wav2Lip, local model adapters, or OmniRT remote inference.

### CUDA / Driver / PyTorch Notes

First check that the host can see the GPU:

```bash
nvidia-smi
```

Then check whether PyTorch works inside the Python environment:

```bash
python - <<'PY'
import torch
print("cuda available:", torch.cuda.is_available())
print("device count:", torch.cuda.device_count())
PY
```

If `torch.cuda.is_available()` returns `False`, check the NVIDIA driver, CUDA runtime, PyTorch wheel, and active virtual environment.

### GPU Memory Recommendations

| Path | Recommended Resource | Notes |
| --- | --- | --- |
| QuickTalk | 3090 / 4090 class GPU recommended | Good first real video rendering path. |
| Wav2Lip | 8 GB+ VRAM to start | Lightweight lip-sync validation. |
| FlashTalk / FlashHead | 4090 / A100 or multi-GPU | Prefer OmniRT or a dedicated inference service. |

## Linux + Ascend NPU Notes

### CANN Environment

Ascend NPU paths depend on the host driver and CANN. Usually, load the environment first:

```bash
test -f /usr/local/Ascend/ascend-toolkit/set_env.sh && echo "CANN is ready"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
npu-smi info
```

### torch_npu

`torch_npu` must match PyTorch, driver, and CANN versions. If import fails, first confirm that CANN environment variables are active:

```bash
python - <<'PY'
import torch
import torch_npu
print("torch:", torch.__version__)
print("torch_npu imported")
PY
```

### Suitable Model Path

Ascend environments are better suited for enterprise private deployment and high-quality model-service validation. Currently, OpenTalking should run as the orchestration layer, while heavyweight models run behind OmniRT or a dedicated model service. For first bring-up and debugging, source installation is recommended so driver, CANN, model logs, and weight paths are visible on the host.

## Windows / WSL Notes

### WSL2 Recommended

Windows users should use WSL2 + Ubuntu. This reuses the Linux Python, Node.js, FFmpeg, and Docker ecosystem, and keeps paths and commands closer to the documentation.

Native Windows can be used for Mock mode and frontend development experiments, but it is not the primary validation environment. Real model dependencies, FFmpeg, GPU runtime, and some Python packages are more likely to hit compatibility issues on Windows.

## China Mainland Mirrors

### Python Mirrors

With `uv`:

```bash
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
uv sync --extra dev --python 3.11
```

With `pip`:

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
pip install -e ".[dev]"
```

### npm Mirrors

If frontend dependency installation is slow:

```bash
npm config set registry https://registry.npmmirror.com
cd apps/web
npm ci
```

### Hugging Face / ModelScope

If Hugging Face downloads are slow, temporarily set a mirror:

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

If a model is also available on ModelScope, you can download it from ModelScope and manually arrange files into the directory layout required by the documentation.

### Model Weight Downloads

Model weights are recommended under repository-root `models/`, for example:

```text
models/
  quicktalk/
    checkpoints/
```

In offline environments, as long as the final directory structure and filenames match the corresponding model documentation, the download method does not matter.

## Common Platform Issues

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| `ffmpeg: not found` | FFmpeg is missing | macOS: `brew install ffmpeg`; Ubuntu: `apt install ffmpeg`. |
| `npm ci` fails | Node.js too old or network unstable | Use Node.js 18+ and switch npm mirror if needed. |
| `torch.cuda.is_available()` is `False` | CUDA / driver / PyTorch mismatch | Check `nvidia-smi`, active venv, and PyTorch install source. |
| `npu-smi: command not found` | CANN environment not loaded | Run `source /usr/local/Ascend/ascend-toolkit/set_env.sh`. |
| Model weights not found | Path or filename mismatch | Use `stat` to check key files according to the model documentation. |
