# Deploying OpenTalking + OmniRT + QuickTalk on Windows

> This guide targets Windows laptop deployment scenarios. The goal is to go from `git clone` to running OpenTalking + OmniRT + QuickTalk in WSL2 Ubuntu, and completing an E2E Benchmark.

---

## 0. Final Deployment Structure

```text
Windows Host
  └── WSL2 Ubuntu
        ├── OpenTalking: Web / API / Session orchestration
        ├── OmniRT: QuickTalk inference backend
        └── CUDA: RTX 3050 Laptop GPU
```

Recommended directory structure:

```text
/root/test/
├── opentalking/
│   ├── .venv/
│   ├── apps/
│   ├── configs/
│   ├── scripts/
│   └── models/quicktalk/checkpoints/
├── omnirt/
│   ├── .venv/
│   └── models/quicktalk/
└── models/
    └── quicktalk -> /root/test/opentalking/models/quicktalk
```

Place code in WSL2's own Linux filesystem (e.g., `/root/test` or `/home/<user>/test`), not directly under `/mnt/d/...`.

---

## 1. Windows-Side Prerequisites

### 1.1 NVIDIA Driver

Confirm the GPU and driver work on Windows:

```powershell
nvidia-smi
```

Expected output:

```text
NVIDIA GeForce RTX 3050 Laptop GPU
CUDA Version: 13.0
```

Note: The `CUDA Version` here indicates the highest CUDA version supported by the driver, not that CUDA Toolkit must be installed. PyTorch can be installed with CUDA wheels directly.

---

### 1.2 Install and Verify WSL2

In an administrator PowerShell:

```powershell
wsl --version
wsl --status
```

Expected:

```text
Default version: 2
```

If Ubuntu is not installed yet:

```powershell
wsl --install -d Ubuntu-22.04
```

For a manually imported Ubuntu:

```powershell
wsl --import Ubuntu-22.04 D:\wsl\Ubuntu-22.04 D:\wsl\downloads\ubuntu-22.04-wsl.rootfs.tar.gz --version 2
```

Enter WSL2:

```powershell
wsl -d Ubuntu-22.04
```

Verify GPU in WSL2:

```bash
nvidia-smi
```

If WSL2 can see the RTX 3050, the CUDA inference prerequisites are met.

---

### 1.3 WSL2 Network Mode Selection

WSL2 supports two network modes that directly impact OpenTalking's WebRTC real-time audio/video streaming and browser microphone access.

**.wslconfig** (located at `%USERPROFILE%\.wslconfig` on Windows):

```ini
[wsl2]
networkingMode=NAT        # default mode
# networkingMode=Mirrored
```

After making changes, run `wsl --shutdown` and reopen the WSL2 terminal for changes to take effect.

**Comparison**:

| | NAT (default) | Mirrored |
|---|---|---|
| WebRTC ICE connectivity | ✅ Working (when accessed via WSL2 IP) | ⚠️ ICE candidates may fail |
| Browser access | `http://<WSL2-IP>:5280` | `http://localhost:5280` |
| Microphone permission | Requires adding insecure origin whitelist in browser | localhost works directly |
| Service startup compatibility | ✅ Normal | ⚠️ May fail in some scenarios |

**Recommendation**:

- Use **NAT mode** for daily development and debugging. Get the WSL2 IP with `hostname -I` and access via that address.
- If the WSL2 IP changes after a restart, run `hostname -I` again.
- For one-click install scripts or first-time setup, prefer **NAT mode**.

**Enabling microphone in NAT mode**:

Non-localhost HTTP origins are not treated as secure contexts by browsers, so `getUserMedia` access is blocked. Choose one of these workarounds:

- **Edge**: Navigate to `edge://flags/#unsafely-treat-insecure-origin-as-secure`, enter `http://<WSL2-IP>:5280`, set to Enabled, and restart.
- **Chrome**: Close all Chrome windows, then run in PowerShell:
  ```powershell
  & "C:\Program Files\Google\Chrome\Application\chrome.exe" --unsafely-treat-insecure-origin-as-secure="http://<WSL2-IP>:5280" --user-data-dir="%TEMP%\chrome-opentalking"
  ```

---

## 2. WSL2 Base Dependencies

The following commands run inside WSL2 Ubuntu. If running as root, `sudo` is not needed; otherwise prepend `sudo` to `apt` commands.

```bash
apt update
apt install -y \
  python3-pip python3-venv python3-dev \
  build-essential pkg-config \
  curl wget git git-lfs rsync unzip \
  ffmpeg nodejs npm jq \
  iproute2 procps psmisc \
  libgl1 libglib2.0-0

git lfs install
```

Check basic tools:

```bash
python3 --version
ffmpeg -version
node --version
npm --version
nvidia-smi
```

---

## 3. Clone from GitHub

Enter the working directory:

```bash
mkdir -p /root/test
cd /root/test
```

Clone both repositories:

```bash
git clone https://github.com/datascale-ai/opentalking.git
git clone https://github.com/datascale-ai/omnirt.git
```

The final structure should be:

```text
/root/test/opentalking
/root/test/omnirt
```

Verify:

```bash
ls /root/test/opentalking
ls /root/test/omnirt
```

### Path Notes

If the code already exists on Windows, copy it to WSL2:

```bash
rsync -a --info=progress2 /mnt/d/test_opentalking/opentalking/ /root/test/opentalking/
rsync -a --info=progress2 /mnt/d/test_opentalking/omnirt/ /root/test/omnirt/
```

If the code is already downloaded on a server, sync it to WSL2:

```bash
rsync -avP root@<your-server-ip>:/root/lyf/temp/opentalking/ /root/test/opentalking/
rsync -avP root@<your-server-ip>:/root/lyf/temp/omnirt/ /root/test/omnirt/
```

---

## 4. Install uv and Configure Mirrors

Install uv in WSL2:

```bash
python3 -m pip install -U uv
```

If `uv` is not in PATH:

```bash
export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
echo 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

Verify:

```bash
uv --version
```

Write commonly used mirror environment variables:

```bash
cat >> ~/.bashrc <<'EOF'
export PIP_INDEX_URL=https://pypi.org/simple
export UV_DEFAULT_INDEX=https://pypi.org/simple
export UV_INDEX_URL=https://pypi.org/simple
export HF_ENDPOINT=https://huggingface.co
export npm_config_registry=https://registry.npmjs.org
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb=128
EOF

source ~/.bashrc
```

---

## 5. Configure OpenTalking Environment

Enter OpenTalking:

```bash
cd /root/test/opentalking
```

Create an isolated virtual environment:

```bash
uv venv --python python3 .venv
source .venv/bin/activate
```

Confirm Python path:

```bash
which python
```

Expected:

```text
/root/test/opentalking/.venv/bin/python
```

Install base packages:

```bash
uv pip install -U pip setuptools wheel
```

Install OpenTalking dependencies:

```bash
uv pip install -e ".[dev,models]"
```

Install CUDA PyTorch:

```bash
uv pip install \
  torch==2.9.1+cu128 \
  torchvision==0.24.1+cu128 \
  torchaudio==2.9.1+cu128 \
  --find-links https://download.pytorch.org/whl/cu128/
```

Verify CUDA:

```bash
python -c "import torch; print('torch=', torch.__version__); print('torch cuda=', torch.version.cuda); print('cuda=', torch.cuda.is_available()); print('gpu=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

Expected output:

```text
torch= 2.9.1+cu128
torch cuda= 12.8
cuda= True
gpu= NVIDIA GeForce RTX 3050 Laptop GPU
```

### Notes

Installing CUDA PyTorch on Linux/WSL2 will pull `nvidia-cudnn-cu12`, `nvidia-cublas-cu12`, `triton`, and other dependencies — these are large, which is normal. The key is that `cuda=True` must be confirmed.

---

## 6. Prepare QuickTalk Weights

QuickTalk weights should be placed at:

```text
/root/test/opentalking/models/quicktalk/checkpoints/
```

The complete structure should look like:

```text
checkpoints/
├── quicktalk.pth
├── repair.npy
├── chinese-hubert-large/
│   ├── config.json
│   ├── preprocessor_config.json
│   └── pytorch_model.bin
└── auxiliary/models/buffalo_l/
    ├── det_10g.onnx
    ├── w600k_r50.onnx
    ├── 2d106det.onnx
    └── ...
```

Check key files:

```bash
cd /root/test/opentalking

ls -lh models/quicktalk/checkpoints/quicktalk.pth
ls -lh models/quicktalk/checkpoints/repair.npy
ls -lh models/quicktalk/checkpoints/chinese-hubert-large/pytorch_model.bin
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/w600k_r50.onnx
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/2d106det.onnx
```

### Path Notes

When starting QuickTalk in OmniRT, point directly to the `checkpoints` directory:

```bash
export OMNIRT_QUICKTALK_MODEL_ROOT=/root/test/opentalking/models/quicktalk/checkpoints
```

If the benchmark script expects `/root/test/models/quicktalk`, create a symlink:

```bash
mkdir -p /root/test/models
ln -sfn /root/test/opentalking/models/quicktalk /root/test/models/quicktalk
```

---

## 7. Configure OmniRT Environment

Enter OmniRT:

```bash
cd /root/test/omnirt
```

Create an isolated virtual environment:

```bash
uv venv --python python3 .venv
source .venv/bin/activate
```

Confirm Python path:

```bash
which python
```

Expected:

```text
/root/test/omnirt/.venv/bin/python
```

Install dependencies:

```bash
uv pip install -U pip setuptools wheel

uv pip install -e ".[dev,server,quicktalk-cuda]" \
  --find-links https://download.pytorch.org/whl/cu128/
```

If needed, reinstall CUDA torch:

```bash
uv pip install \
  torch==2.9.1+cu128 \
  torchvision==0.24.1+cu128 \
  torchaudio==2.9.1+cu128 \
  --find-links https://download.pytorch.org/whl/cu128/
```

Check:

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
which omnirt
omnirt --help
```

Expected:

```text
/root/test/omnirt/.venv/bin/omnirt
```

Sync models to OmniRT:

```bash
mkdir -p /root/test/omnirt/models/quicktalk
rsync -a --info=progress2 \
  /root/test/opentalking/models/quicktalk/ \
  /root/test/omnirt/models/quicktalk/
```

---

## 8. Configure OpenTalking .env

Enter OpenTalking:

```bash
cd /root/test/opentalking
cp -n .env.example .env
```

Recommended key configurations:

```bash
cat >> .env <<'EOF'
OPENTALKING_TTS_DEFAULT_PROVIDER=edge
OPENTALKING_REDIS_MODE=memory
OMNIRT_ENDPOINT=http://127.0.0.1:9000
EOF
```

If LLM / STT is needed, configure the corresponding keys separately:

```bash
OPENTALKING_LLM_API_KEY=your_LLM_API_KEY
OPENTALKING_STT_DASHSCOPE_API_KEY=your_STT_API_KEY
```

### Notes

LLM, TTS, and STT are independent providers. Edge TTS does not require a key and is best for initially verifying the pipeline. An expired or invalid DashScope key will affect LLM / STT but does not mean QuickTalk inference is unavailable.

---

## 9. Start OmniRT QuickTalk Backend

Open a new WSL2 terminal and enter OmniRT:

```bash
cd /root/test/omnirt
source .venv/bin/activate
```

Set environment variables:

```bash
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb=128

export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_MODEL_ROOT=/root/test/opentalking/models/quicktalk/checkpoints
export OMNIRT_QUICKTALK_DEVICE=cuda:0
export OMNIRT_QUICKTALK_HUBERT_DEVICE=cuda:0
```

Start:

```bash
.venv/bin/python -m omnirt.cli.main serve-avatar-ws \
  --host 0.0.0.0 \
  --port 9000 \
  --compat flashtalk \
  --backend cuda \
  --avatar-runtime fake
```

Key parameters:

| Parameter | Purpose |
| --- | --- |
| `OMNIRT_QUICKTALK_RUNTIME=1` | Enable QuickTalk runtime |
| `OMNIRT_QUICKTALK_MODEL_ROOT=.../checkpoints` | Point to QuickTalk weights directory |
| `--compat flashtalk` | Compatible with OpenTalking WebSocket protocol |
| `--avatar-runtime fake` | Let QuickTalk runtime take effect, avoiding the FlashTalk resident path |

---

## 10. Start OpenTalking

Open another WSL2 terminal and enter OpenTalking:

```bash
cd /root/test/opentalking
source .venv/bin/activate
```

Start:

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000 \
  --host 0.0.0.0
```

Frontend URL:

```text
http://127.0.0.1:5173
```

Verify QuickTalk connection status:

```bash
curl -s http://127.0.0.1:8000/models \
  | python3 -c "import sys,json; [print(s) for s in json.load(sys.stdin)['statuses'] if s['id']=='quicktalk']"
```

Expected:

```text
connected=true
reason=omnirt
```

Check GPU memory:

```bash
nvidia-smi --query-gpu=memory.used --format=csv,noheader
```

---

## 11. Common Path Issues

| Location | Correct approach |
| --- | --- |
| Code directory | Place in `/root/test/opentalking` and `/root/test/omnirt` |
| OpenTalking venv | `/root/test/opentalking/.venv` |
| OmniRT venv | `/root/test/omnirt/.venv` |
| QuickTalk weights | `/root/test/opentalking/models/quicktalk/checkpoints` |
| OmniRT QuickTalk root | Point to `.../checkpoints` |
| Benchmark compatibility path | `ln -sfn /root/test/opentalking/models/quicktalk /root/test/models/quicktalk` |
| Low-VRAM config | `resolution=160/128`, `batch=1`, `HuBERT=cpu` |

---

## 12. Final Checklist

Before running the benchmark, verify each item:

```bash
# WSL2 GPU
nvidia-smi

# OpenTalking environment
cd /root/test/opentalking
source .venv/bin/activate
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"

# QuickTalk weights
ls -lh models/quicktalk/checkpoints/quicktalk.pth
ls -lh models/quicktalk/checkpoints/chinese-hubert-large/pytorch_model.bin
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx

# OmniRT environment
cd /root/test/omnirt
source .venv/bin/activate
which omnirt
omnirt --help

# Frontend / basic tools
ffmpeg -version
node --version
npm --version
```

If all checks pass, run:

```bash
cd /root/test/opentalking
source .venv/bin/activate
bash scripts/run_opentalking_e2e_benchmark.sh \
  --tester xxx \
  --model quicktalk \
  --backend omnirt \
  --gpu-index 0 \
  --timeout 300
```

---

## 13. Summary

Deploying OpenTalking + OmniRT + QuickTalk on Windows is best done in WSL2:

```text
Windows Host
  └── WSL2 Ubuntu
        ├── OpenTalking .venv
        ├── OmniRT .venv
        ├── QuickTalk checkpoints
        ├── OmniRT QuickTalk runtime
        └── E2E Benchmark
```

Advantages of this approach:

- More compatible with official bash scripts;
- Convenient use of Linux toolchains;
- CUDA can access the RTX 3050 normally through WSL2;
- OpenTalking and OmniRT environments are isolated, making troubleshooting clearer;
- The path from environment setup to full E2E benchmark is fully reproducible.
