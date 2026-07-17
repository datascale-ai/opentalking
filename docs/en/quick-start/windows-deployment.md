# Windows WSL2 Deployment for OpenTalking + QuickTalk

This guide targets a single-machine Windows + WSL2 Ubuntu deployment. Start with the recommended QuickTalk local mode. Use QuickTalk OmniRT mode only when you need to serviceize the avatar runtime or split OpenTalking from the inference backend.

## 1. Route Selection

### 1.1 Recommended Route: QuickTalk Local Mode

Use this route for single-machine WSL2, one GPU, and quick validation of the realtime digital-human pipeline. OpenTalking loads the QuickTalk adapter in process, so OmniRT does not need to run separately.

### 1.2 Advanced Route: QuickTalk OmniRT Mode

Use this route for serviceized deployments, split avatar runtime, or later multi-service expansion. It requires an additional OmniRT QuickTalk backend.

## 2. Recommended Directory Structure

Keep code, runtime checkouts, and model weights separated. A recommended WSL2 layout is:

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
│   ├── .venv/
│   ├── apps/
│   ├── docs/
│   └── scripts/
├── model-repos/
│   └── omnirt/
│       └── .venv/
├── models/
│   └── quicktalk/
│       └── checkpoints/
│           ├── quicktalk.pth
│           ├── repair.npy
│           ├── chinese-hubert-large/
│           └── auxiliary/models/buffalo_l/
├── logs/
└── run/
```

Place the workspace in the WSL2 Linux filesystem, such as `$HOME/opentalking-workspace`, not under `/mnt/c` or `/mnt/d`.

## 3. Port Convention

| Service | Port | Used by |
| --- | --- | --- |
| OpenTalking API | `8210` | Local and OmniRT routes |
| OpenTalking Web UI | `5173` | Local and OmniRT routes |
| OmniRT | `9000` | OmniRT route only |

Inside WSL2, the OpenTalking / QuickTalk startup commands keep the same backend, model, weight-path, and OmniRT endpoint conventions as the Linux deployment docs. Windows browser access needs an explicit `--host 0.0.0.0`, and the Web UI port is standardized on the current frontend default, `5173`.

## 4. Windows-Side Prerequisites

### 4.1 NVIDIA Driver

Confirm the GPU and driver in Windows PowerShell:

```powershell
nvidia-smi
```

Seeing the NVIDIA GPU and driver-supported CUDA version is enough. The CUDA Version shown here is the driver capability, not a requirement to install CUDA Toolkit on Windows.

### 4.2 Install and Verify WSL2

In an administrator PowerShell:

```powershell
wsl --version
wsl --status
```

If Ubuntu is not installed yet:

```powershell
wsl --install -d Ubuntu-22.04
```

Enter WSL2:

```powershell
wsl -d Ubuntu-22.04
```

Verify that the GPU is visible inside WSL2:

```bash
nvidia-smi
```

## 5. WSL2 Network and Browser Microphone

Use WSL2 NAT mode by default, and open the Web UI from the Windows browser through the WSL2 IP.

Get the WSL2 IP:

```bash
hostname -I | awk '{print $1}'
```

Open from the Windows browser:

```text
http://<WSL2-IP>:5173
```

If WSL2 localhost forwarding works in your environment, this can also work:

```text
http://localhost:5173
```

In NAT mode, a non-localhost HTTP address is not a browser secure context, so microphone access can be blocked. Add the current Web UI address to the browser allowlist.

Edge:

```text
edge://flags/#unsafely-treat-insecure-origin-as-secure
Enter http://<WSL2-IP>:5173
```

Chrome PowerShell example:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --unsafely-treat-insecure-origin-as-secure="http://<WSL2-IP>:5173" `
  --user-data-dir="%TEMP%\chrome-opentalking"
```

## 6. WSL2 Base Dependencies

Run these commands inside WSL2 Ubuntu. If you are root, `sudo` is not needed; otherwise prepend `sudo` to the `apt` commands.

```bash
apt update
apt install -y \
  python3-pip python3-venv python3-dev \
  build-essential pkg-config \
  curl wget git git-lfs rsync unzip \
  ffmpeg nodejs jq \
  iproute2 procps psmisc \
  libgl1 libglib2.0-0

git lfs install
```

If `nodejs` comes from NodeSource, the `nodejs` package usually already includes `npm`. Do not install Ubuntu's separate `npm` package at the same time, or you may hit `nodejs : Conflicts: npm`. After installing the base dependencies, check:

```bash
node --version
npm --version
```

The OpenTalking Web UI uses Vite 5, which requires Node.js `18+`. Some Windows WSL Ubuntu installations still get Node.js `12.x` from the default system repository, which can break frontend dependency installation or startup. If `node --version` is lower than `v18`, upgrade Node.js first:

```bash
node -e "const m=Number(process.versions.node.split('.')[0]); if (m < 18) process.exit(1)" \
  || curl -fsSL https://deb.nodesource.com/setup_20.x | bash -

apt install -y nodejs

node --version
npm --version
node -e "const m=Number(process.versions.node.split('.')[0]); if (m < 18) throw new Error('Node.js 18+ required')"
```

Only install `npm` separately when `npm --version` is missing and you are using Ubuntu's official `nodejs` package:

```bash
apt install -y npm
```

Check the base tools:

```bash
python3 --version
ffmpeg -version
node --version
npm --version
nvidia-smi
```

## 7. Prepare the Workspace

Prefer a WSL2 Linux filesystem path such as `$HOME/opentalking-workspace` for the runtime workspace. Do not run the project directly from a Windows-mounted path. If you must copy code from a Windows disk, treat `/mnt/<drive>/...` only as an example source path, then sync it into the WSL2 Linux filesystem.

Define every path variable before using it:

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_MODEL_REPO_ROOT="${OPENTALKING_MODEL_REPO_ROOT:-$DIGITAL_HUMAN_HOME/model-repos}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OMNIRT_REPO="${OMNIRT_REPO:-$OPENTALKING_MODEL_REPO_ROOT/omnirt}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
export OMNIRT_QUICKTALK_MODEL_ROOT="${OMNIRT_QUICKTALK_MODEL_ROOT:-$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints}"

mkdir -p \
  "$DIGITAL_HUMAN_HOME" \
  "$OPENTALKING_MODEL_ROOT" \
  "$OPENTALKING_MODEL_REPO_ROOT" \
  "$OPENTALKING_QUICKTALK_ASSET_ROOT" \
  "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"
```

Clone OpenTalking:

```bash
git clone https://github.com/datascale-ai/opentalking.git "$OPENTALKING_HOME"
cd "$OPENTALKING_HOME"
```

If the repository is already cloned, enter the existing directory:

```bash
cd "$OPENTALKING_HOME"
```

## 8. Install uv and Configure Mirrors

```bash
python3 -m pip install -U uv
```

If `uv` is not in `PATH`:

```bash
export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
echo 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

Check:

```bash
uv --version
```

When network access is slow, set mirrors as needed:

```bash
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export npm_config_registry="${npm_config_registry:-https://registry.npmmirror.com}"
```

## 9. Prepare QuickTalk Weights

OpenTalking local asset root:

```text
$OPENTALKING_QUICKTALK_ASSET_ROOT
```

QuickTalk weight directory:

```text
$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints
```

Download or place the weights:

```bash
cd "$OPENTALKING_HOME"

export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"

mkdir -p "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

uv tool run --from "huggingface_hub[cli]" hf download datascale-ai/quicktalk \
  --local-dir "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"
```

Check the required files:

```bash
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/quicktalk.pth"
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/repair.npy"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/chinese-hubert-large"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l"
```

QuickTalk local also needs a template video for real sessions. Prefer avatars that have `source_video` / `template_video` metadata, or prepared `quicktalk/template_*.mp4` files under the avatar directory.

```bash
find "$OPENTALKING_HOME/examples/avatars" -type f \( -path '*/quicktalk/template_*.mp4' -o -path '*/source/*.mp4' \) | sort | head
```

Do not set `OPENTALKING_QUICKTALK_TEMPLATE_VIDEO` in the service startup environment. It is a global template override and forces every QuickTalk realtime session to use the same video template. If the user selects another avatar, the picture can switch back to the avatar from that global template as soon as lip generation starts. Only pass a template explicitly for one-off offline debugging commands.

Path relationship:

- OpenTalking local asset root: `$OPENTALKING_QUICKTALK_ASSET_ROOT`
- Weight file directory: `$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints`
- OmniRT QuickTalk model root: `$OMNIRT_QUICKTALK_MODEL_ROOT`

This guide points the OmniRT QuickTalk model root to the same weight directory:

```bash
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
export OMNIRT_QUICKTALK_MODEL_ROOT="${OMNIRT_QUICKTALK_MODEL_ROOT:-$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints}"
```

If `OMNIRT_QUICKTALK_MODEL_ROOT` is unset, the current helper script defaults to `$OMNIRT_MODEL_ROOT/quicktalk`. This Windows guide sets it explicitly to `$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints` so users do not have to guess the difference between `models/quicktalk` and `models/quicktalk/checkpoints`.

The current helper script checks that `$OMNIRT_QUICKTALK_MODEL_ROOT` contains `quicktalk.pth`, `repair.npy`, `chinese-hubert-large/`, and `auxiliary/models/buffalo_l/`.

## 10. Recommended Route: Start QuickTalk Local

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11

export OPENTALKING_TORCH_DEVICE="${OPENTALKING_TORCH_DEVICE:-cuda:0}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OPENTALKING_QUICKTALK_WORKER_CACHE="${OPENTALKING_QUICKTALK_WORKER_CACHE:-1}"

bash scripts/start_unified.sh \
  --backend local \
  --model quicktalk \
  --api-port 8210 \
  --web-port 5173 \
  --host 0.0.0.0
```

Verify:

```bash
curl -fsS http://127.0.0.1:8210/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/models | python3 -m json.tool
```

Confirm the `quicktalk` status reports `backend=local`, and that `connected` / `healthy` style fields indicate it is available. Actual fields depend on the current `/models` response.

`/health` and `/models` confirm that the service process, model weights, and QuickTalk backend are available. Full conversations, live STT, and end-to-end benchmarks also depend on LLM / STT / TTS configuration. If the required API keys are not configured, local QuickTalk can still show as available in `/models`, while sessions or benchmarks may fail during speech or text generation.

Open from the Windows browser:

```text
http://<WSL2-IP>:5173
```

If localhost forwarding works:

```text
http://localhost:5173
```

## 11. Advanced Route: Start QuickTalk OmniRT

The OmniRT route requires an OmniRT checkout and virtual environment. `scripts/quickstart/start_omnirt_quicktalk.sh` starts the OmniRT QuickTalk backend from `$OMNIRT_REPO`.

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_MODEL_REPO_ROOT="${OPENTALKING_MODEL_REPO_ROOT:-$DIGITAL_HUMAN_HOME/model-repos}"
export OMNIRT_REPO="${OMNIRT_REPO:-$OPENTALKING_MODEL_REPO_ROOT/omnirt}"

mkdir -p "$OPENTALKING_MODEL_REPO_ROOT"

git clone https://github.com/datascale-ai/omnirt.git "$OMNIRT_REPO"
cd "$OMNIRT_REPO"
uv sync --extra server --extra quicktalk-cuda --python 3.11
```

Install `quicktalk-cuda` here so the first OmniRT QuickTalk startup does not have to download and build CUDA dependencies. If you only run `uv sync --extra server --python 3.11`, the startup script will still install `quicktalk-cuda` in the background, and a fresh environment may exceed the script's 180-second readiness wait.

If OmniRT is already cloned, enter the directory and confirm the virtual environment exists. If the QuickTalk CUDA dependencies have not been installed yet, run the sync once:

```bash
cd "$OMNIRT_REPO"
test -f .venv/bin/activate
uv sync --extra server --extra quicktalk-cuda --python 3.11
```

Start the OmniRT QuickTalk backend:

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_MODEL_REPO_ROOT="${OPENTALKING_MODEL_REPO_ROOT:-$DIGITAL_HUMAN_HOME/model-repos}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OPENTALKING_AVATARS_DIR="${OPENTALKING_AVATARS_DIR:-$OPENTALKING_HOME/examples/avatars}"
export OMNIRT_REPO="${OMNIRT_REPO:-$OPENTALKING_MODEL_REPO_ROOT/omnirt}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
export OMNIRT_QUICKTALK_MODEL_ROOT="${OMNIRT_QUICKTALK_MODEL_ROOT:-$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints}"
export OMNIRT_ALLOWED_FRAME_ROOTS="${OMNIRT_ALLOWED_FRAME_ROOTS:-$OPENTALKING_AVATARS_DIR}"

cd "$OPENTALKING_HOME"

bash scripts/quickstart/start_omnirt_quicktalk.sh \
  --device cuda:0 \
  --port 9000 \
  --host 0.0.0.0
```

If the first startup reports:

```text
OmniRT QuickTalk did not become ready in 180s
```

it usually means the first `quicktalk-cuda` dependency installation has not finished yet. For example, the script may still be running `uv sync --extra server --extra quicktalk-cuda --python 3.11` to download or build CUDA packages. Handle it by completing the dependency sync first, then starting OmniRT again:

```bash
cd "$OMNIRT_REPO"
uv sync --extra server --extra quicktalk-cuda --python 3.11

cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_quicktalk.sh \
  --device cuda:0 \
  --port 9000 \
  --host 0.0.0.0
```

If the previous startup script timed out but the log still shows dependency installation continuing, wait until that install finishes and then rerun `start_omnirt_quicktalk.sh`. After the dependencies are installed, the next startup should become ready much faster.

Then start OpenTalking connected to OmniRT:

```bash
cd "$OPENTALKING_HOME"

bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8210 \
  --web-port 5173 \
  --host 0.0.0.0
```

Verify:

```bash
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/models | python3 -m json.tool
```

Confirm the `quicktalk` status reports `backend=omnirt`, and that `connected` / `healthy` style fields indicate it is available. Actual fields depend on the current `/models` response.

If session startup reports:

```text
RuntimeError: audio2video init failed: template_video requires configured allowed frame roots.
```

OmniRT was not configured with a readable avatar template-video directory, or `OMNIRT_ALLOWED_FRAME_ROOTS` does not include the `template_video` path sent by OpenTalking. Stop OmniRT, export the allowed frame root, and start it again:

```bash
cd "$OPENTALKING_HOME"
bash scripts/quickstart/stop_all.sh

export OPENTALKING_AVATARS_DIR="${OPENTALKING_AVATARS_DIR:-$OPENTALKING_HOME/examples/avatars}"
export OMNIRT_ALLOWED_FRAME_ROOTS="$OPENTALKING_AVATARS_DIR"

bash scripts/quickstart/start_omnirt_quicktalk.sh \
  --device cuda:0 \
  --port 9000 \
  --host 0.0.0.0
```

If your avatars or template videos live elsewhere, include those directories in `OMNIRT_ALLOWED_FRAME_ROOTS` too. Use a colon to separate multiple directories:

```bash
export OMNIRT_ALLOWED_FRAME_ROOTS="$OPENTALKING_AVATARS_DIR:/path/to/extra/avatar-root"
```

## 12. Common Path Issues

| Location | Correct approach |
| --- | --- |
| Code directory | Keep OpenTalking at `$OPENTALKING_HOME`, normally `$DIGITAL_HUMAN_HOME/opentalking`. |
| OmniRT checkout | Keep OmniRT at `$OMNIRT_REPO`, normally `$DIGITAL_HUMAN_HOME/model-repos/omnirt`. |
| OpenTalking virtualenv | Use `$OPENTALKING_HOME/.venv`; do not reuse the OmniRT virtualenv. |
| OmniRT virtualenv | Use `$OMNIRT_REPO/.venv`; install OmniRT server dependencies there. |
| Model root | Keep large model files under `$OPENTALKING_MODEL_ROOT`, normally `$DIGITAL_HUMAN_HOME/models`. |
| QuickTalk asset root | Use `$OPENTALKING_QUICKTALK_ASSET_ROOT`, normally `$OPENTALKING_MODEL_ROOT/quicktalk`. |
| QuickTalk checkpoint directory | Put `quicktalk.pth`, `repair.npy`, `chinese-hubert-large/`, and `auxiliary/models/buffalo_l/` under `$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints`. |
| OmniRT QuickTalk root | Set `$OMNIRT_QUICKTALK_MODEL_ROOT` to the same checkpoint directory when using the OmniRT route. |
| OmniRT template-video allowlist | When using the OmniRT route, `$OMNIRT_ALLOWED_FRAME_ROOTS` must include the active avatar root, usually `$OPENTALKING_HOME/examples/avatars` or `$OPENTALKING_AVATARS_DIR`; otherwise OmniRT can report `template_video requires configured allowed frame roots`. |
| Windows-mounted paths | Avoid running from `/mnt/c` or `/mnt/d`; copy or sync into the WSL2 Linux filesystem first. |
| Web UI access | Use `http://<WSL2-IP>:5173` first; use `http://localhost:5173` only when localhost forwarding works. |

If a command reports a missing `repair.npy`, `quicktalk.pth`, HuBERT, or `buffalo_l` path, first check whether the command expects the asset root (`models/quicktalk`) or the checkpoint directory (`models/quicktalk/checkpoints`).

If frontend dependency installation or startup reports that Node is too old, run the NodeSource upgrade commands in section 6 and confirm `node --version` is `v18` or newer.

## 13. Stop Services

Stop the OpenTalking API, Web UI, and OmniRT processes started by quickstart scripts or `scripts/start_unified.sh`:

```bash
cd "$OPENTALKING_HOME"
bash scripts/quickstart/stop_all.sh
```

To fully restart WSL2, run this from Windows PowerShell:

```powershell
wsl --shutdown
```

## 14. Final Checklist

After the service health checks pass, first run the QuickTalk offline generation check. This check depends only on the QuickTalk weights, template video, CUDA, HuBERT, and ffmpeg. It does not require LLM / STT / TTS API keys:

```bash
cd "$OPENTALKING_HOME"
mkdir -p "$DIGITAL_HUMAN_HOME/run/quicktalk-bench"

QUICKTALK_BENCH_TEMPLATE_VIDEO="${QUICKTALK_BENCH_TEMPLATE_VIDEO:-$(find "$OPENTALKING_HOME/examples/avatars" -type f \( -path '*/quicktalk/template_*.mp4' -o -path '*/source/*.mp4' \) | sort | head -n 1)}"
test -f "$QUICKTALK_BENCH_TEMPLATE_VIDEO"

ffmpeg -y -hide_banner -loglevel error \
  -i configs/benchmark/input/ttsmaker-file.mp3 \
  -ac 1 -ar 16000 -sample_fmt s16 \
  "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/input.wav"

"$OPENTALKING_HOME/.venv/bin/python" -m apps.cli.quicktalk_bench \
  --asset-root "$OPENTALKING_QUICKTALK_ASSET_ROOT" \
  --template-video "$QUICKTALK_BENCH_TEMPLATE_VIDEO" \
  --audio "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/input.wav" \
  --output "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/output.mp4" \
  --device cuda:0
```

The output file should exist:

```bash
test -f "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/output.mp4"
```

If LLM / STT / TTS credentials are configured, then run the end-to-end benchmark to verify the real OpenTalking + QuickTalk path, not only process startup. The current script requires `--tester`, and the API URL argument is `--api-base-url`:

```bash
cd "$OPENTALKING_HOME"
bash scripts/run_opentalking_e2e_benchmark.sh \
  --tester "$USER" \
  --model quicktalk \
  --backend local \
  --api-base-url http://127.0.0.1:8210
```

If you started the OmniRT route, change `--backend local` to `--backend omnirt`. If the benchmark config file has a `models.quicktalk.backend` value that conflicts with the command line, the model-level backend in the config file takes precedence, so keep it consistent with the command line.

```bash
# WSL2 GPU
nvidia-smi

# OpenTalking repository
cd "$OPENTALKING_HOME"
uv --version

# QuickTalk weights
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/quicktalk.pth"
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/repair.npy"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/chinese-hubert-large"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l"
test -z "${OPENTALKING_QUICKTALK_TEMPLATE_VIDEO:-}"

# After starting either the local or OmniRT route
curl -fsS http://127.0.0.1:8210/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/models | python3 -m json.tool

# After starting the OmniRT route
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | python3 -m json.tool
```

Final Windows Web UI URL:

```text
http://<WSL2-IP>:5173
```

When localhost forwarding works:

```text
http://localhost:5173
```

## 15. Summary

For a first Windows + WSL2 deployment, use the QuickTalk local route: it keeps OpenTalking, QuickTalk, and the Web UI in one startup flow and is easier to debug. Use the OmniRT route when you need a separate inference service, service isolation, or later multi-service expansion. Keep code, virtual environments, and model weights in separate directories, and always verify both `/models` and the Web UI before running the benchmark.
