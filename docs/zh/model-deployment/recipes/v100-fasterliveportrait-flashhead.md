# V100 + FasterLivePortrait + FlashHead 部署配方

> 从零开始，在 NVIDIA V100 (32GB) 上部署实时对话数字人系统
> 包含两套推理方案：FasterLivePortrait（真人驱动）+ FlashHead（AI生成）
> 适用环境：Ubuntu 22.04 + NVIDIA Driver 580 + CUDA 12.x

本页是一份面向 V100 单机的实战部署配方。通用模型说明请先阅读
[FasterLivePortrait](../../avatar_models/fasterliveportrait.md)、[FlashHead](../../avatar_models/flashhead.md) 和
[OmniRT 部署](../backends/omnirt.md)。

---

## 一、系统架构

```
用户浏览器 (5173)
    │
    ▼
OpenTalking 后端 (8000) ── LLM + TTS + WebRTC + 会话管理
    │
    ├── OmniRT (9000) ── FasterLivePortrait（真人视频驱动）
    │
    └── FlashHead Server (8766) ── FlashHead 1.3B（AI 生成）
```

**组件说明：**

| 组件 | 端口 | 功能 |
|---|---|---|
| OpenTalking 前端 | 5173 | 浏览器界面（Vue + Vite） |
| OpenTalking 后端 | 8000 | 编排、LLM 对话、TTS 合成、WebRTC 传输 |
| OmniRT | 9000 | FasterLivePortrait TRT 推理引擎 |
| FlashHead Server | 8766 | FlashHead WebSocket 推理服务 |

---

## 二、服务器基础环境

### 2.1 硬件要求

- GPU：NVIDIA V100 32GB（或同代 Volta 架构）
- 内存：32GB+
- 磁盘：200GB+（模型文件约 50GB）
- 网络：公网 IP，需开放端口 5173、8000、8766、9000、UDP 40000-60000

### 2.2 V100 硬件特性（重要）

| 特性 | 支持情况 | 影响 |
|---|---|---|
| FP16 | ✅ 支持（有 Tensor Core） | 必须用 FP16，不能用 BF16 |
| BF16 | ❌ 不支持 | 新模型默认 BF16，必须手动改 FP16 |
| FP8 | ❌ 不支持 | — |
| FlashAttention 2 | ❌ 不支持（需 SM 80+） | 部分模型需要替换为标准 attention |
| TensorRT | 只支持 8.x（10.x 需 SM 75+） | 必须用 TRT 8.6 |
| torch.compile | ⚠️ 有限支持 | 不同输入形状会触发重编译，建议关闭 |

### 2.3 NVIDIA 驱动安装

```bash
# 检查当前驱动
nvidia-smi

# 如果驱动版本低于 535，需要升级
# 添加 NVIDIA 源
apt install -y software-properties-common
add-apt-repository -y ppa:graphics-drivers/ppa
apt update

# 安装驱动 580（推荐）
apt install -y nvidia-driver-580
reboot

# 验证
nvidia-smi  # 应显示 Driver Version: 580.xx
```

### 2.4 基础软件安装

```bash
apt update && apt install -y \
    python3.10 python3.10-venv python3-pip \
    git git-lfs cmake build-essential \
    ffmpeg libgl1-mesa-glx libglib2.0-0 \
    redis-server

# 配置 pip 国内镜像（服务器在国内必须）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 配置 HuggingFace 镜像
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc
source ~/.bashrc
```

### 2.5 项目目录结构

```bash
mkdir -p /opt/digital-human
cd /opt/digital-human

# 最终目录结构
# /opt/digital-human/
# ├── omnirt/                    # OmniRT 推理引擎
# ├── FasterLivePortrait/        # FLP 模型代码 + 权重
# ├── models/                    # 共享模型权重
# ├── SoulX-FlashHead/           # FlashHead 模型代码
# ├── SoulX-FlashHead-WEB/       # FlashHead 前后端
# │   └── models/                # FlashHead 权重
# ├── opentalking/               # OpenTalking 前后端
# ├── flashhead-env/             # FlashHead Python 环境
# ├── flashhead_server.py        # FlashHead WebSocket 服务器
# └── start_omnirt_trt.sh        # OmniRT 启动脚本
```

---

## 三、FasterLivePortrait 部署（真人驱动方案）

### 3.1 方案特点

- **原理**：录制一段真人视频作为底板，用音频驱动口型、表情、头部运动
- **优点**：真实感最好，输出是"真人"
- **缺点**：推理较慢，长句有轻微卡顿
- **性能**：TRT 优化后约 15-20fps
- **素材需求**：需要预先录制一段正面半身视频（512×512+，光线好，背景干净）

### 3.2 获取代码

```bash
cd /opt/digital-human

# 克隆 FasterLivePortrait
git clone https://github.com/KwaiVGI/LivePortrait.git FasterLivePortrait
cd FasterLivePortrait

# 下载 ONNX 模型（含 warping_spade 等 8 个模型）
# 从 HuggingFace 下载
hf download warmshao/FasterLivePortrait \
    --local-dir ./checkpoints/liveportrait_onnx

# 下载其他必要权重
hf download KwaiVGI/LivePortrait \
    --include "pretrained_weights/*" \
    --local-dir ./checkpoints
```

### 3.3 创建 Python 环境

```bash
python3.10 -m venv /opt/digital-human/omnirt/.venv310
source /opt/digital-human/omnirt/.venv310/bin/activate

# PyTorch（V100 必须用 cu124）
pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu124

# 验证 CUDA
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 输出: True Tesla V100-PCIE-32GB

# 如果报 nvjitlink 符号错误，设置：
export LD_LIBRARY_PATH=$(python -c "import nvidia.nvjitlink; import os; print(os.path.dirname(nvidia.nvjitlink.__file__))")/lib:$LD_LIBRARY_PATH
```

### 3.4 安装 TensorRT 8.6

```bash
# 方案A：系统包安装（推荐）
# 添加 NVIDIA apt 源
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i cuda-keyring_1.1-1_all.deb
apt update
apt install -y tensorrt=8.6.1.6-1+cuda12.0

# Python 绑定
pip install tensorrt==8.6.1

# 方案B：pip 直接安装（如果方案A失败）
pip install tensorrt==8.6.1

# 验证
python -c "import tensorrt; print(tensorrt.__version__)"
# 输出: 8.6.1
```

### 3.5 安装其他依赖

```bash
pip install onnxruntime-gpu==1.17.0
pip install numpy==1.26.4 opencv-python-headless==4.8.1.78
pip install librosa soundfile scipy
```

### 3.6 ONNX → TRT 引擎转换

将 8 个 ONNX 模型转换为 TRT FP16 引擎：

```bash
cd /opt/digital-human/FasterLivePortrait

# 逐个转换（每个耗时 1-5 分钟）
for model in \
    retinaface_det_static \
    face_2dpose_106_static \
    landmark \
    motion_extractor \
    appearance_feature_extractor \
    stitching \
    stitching_lip \
    stitching_eye \
    warping_spade-fix; do
    echo "Converting $model ..."
    python scripts/onnx2trt.py \
        -o ./checkpoints/liveportrait_onnx/${model}.onnx \
        -p fp16
done

# 验证所有 .trt 文件已生成
ls -lh ./checkpoints/liveportrait_onnx/*.trt
# 应有 9 个 .trt 文件
```

### 3.7 编译 GridSample3D 插件

warping_spade 模型需要自定义 TRT 插件：

```bash
# 获取插件源码
git clone https://github.com/NVIDIA/TensorRT.git /tmp/TensorRT
cd /tmp/TensorRT/plugin/gridSamplePlugin

# 编译
mkdir build && cd build
cmake .. -DTRT_LIB_DIR=/usr/lib/x86_64-linux-gnu \
         -DTRT_INCLUDE_DIR=/usr/include/x86_64-linux-gnu \
         -DCUDA_VERSION=12.0
make -j$(nproc)

# 复制插件到模型目录
cp libgrid_sample_3d_plugin.so \
    /opt/digital-human/FasterLivePortrait/checkpoints/liveportrait_onnx/
```

### 3.8 安装 OmniRT

```bash
cd /opt/digital-human
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt

source /opt/digital-human/omnirt/.venv310/bin/activate
pip install -e .
```

### 3.9 启动 OmniRT

创建启动脚本 `/opt/digital-human/start_omnirt_trt.sh`：

```bash
#!/bin/bash
source /opt/digital-human/omnirt/.venv310/bin/activate
export LD_LIBRARY_PATH=/opt/digital-human/omnirt/.venv310/lib/python3.10/site-packages/nvidia/cuda_runtime/lib

export OMNIRT_FASTLIVEPORTRAIT_RUNTIME=true
export OMNIRT_FASTLIVEPORTRAIT_ROOT=/opt/digital-human/FasterLivePortrait
export OMNIRT_FASTLIVEPORTRAIT_CHECKPOINTS_DIR=/opt/digital-human/FasterLivePortrait/checkpoints
export OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml
export OMNIRT_FASTLIVEPORTRAIT_LOAD_MODELS=true

cd /opt/digital-human/omnirt
python -c "from omnirt.server.avatar_app import create_avatar_app; import uvicorn; app = create_avatar_app(default_backend='cuda'); uvicorn.run(app, host='0.0.0.0', port=9000)"
```

```bash
chmod +x /opt/digital-human/start_omnirt_trt.sh
bash /opt/digital-human/start_omnirt_trt.sh
```

验证：
```bash
curl http://127.0.0.1:9000/v1/audio2video/models
# 应返回 fasterliveportrait connected=true
```

### 3.10 FasterLivePortrait 参数调优

文件：`opentalking/configs/synthesis/fasterliveportrait.yaml`

```yaml
# 分辨率（与底板视频匹配）
width: 448
height: 900
fps: 25

# 动画区域：all=全脸，lip=只动嘴
animation_region: all

# 运动幅度（越大动作越大）
head_motion_multiplier: 0.8      # 头部运动
expression_multiplier: 1.5       # 表情
mouth_open_multiplier: 1.25      # 嘴张开幅度
mouth_corner_multiplier: 0.85    # 嘴角

# 音频分块
chunk_samples: 16000
emit_frames_per_chunk: 25

# 帧插值（V100 上可能更卡，建议关闭）
disable_frame_interpolation: true
```

---

## 四、FlashHead 部署（AI 生成方案）

### 4.1 方案特点

- **原理**：扩散模型，从一张参考图 + 音频实时生成说话视频
- **优点**：速度极快（69fps），不卡顿，只需一张照片
- **缺点**：AI 生成痕迹明显，真实感不如真人驱动
- **性能**：V100 FP16，单次推理 0.48s/33帧，峰值显存 4.94GB
- **素材需求**：只需一张正面照片（PNG 格式，512×512+，光线好）

### 4.2 创建 Python 环境

```bash
python3.10 -m venv /opt/digital-human/flashhead-env
source /opt/digital-human/flashhead-env/bin/activate

# PyTorch
pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu124

# 解决 nvjitlink 符号问题
export LD_LIBRARY_PATH=/opt/digital-human/flashhead-env/lib/python3.10/site-packages/nvidia/nvjitlink/lib:$LD_LIBRARY_PATH

# 验证
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 安装依赖
pip install fastapi uvicorn websockets librosa soundfile \
    opencv-python-headless imageio pillow transformers accelerate \
    openai edge-tts einops diffusers av xfuser easydict \
    scikit-image loguru mediapipe==0.10.9 pydantic-settings \
    -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4.3 获取模型代码

```bash
cd /opt/digital-human
git clone https://github.com/Soul-AILab/SoulX-FlashHead.git
```

### 4.4 下载模型权重

```bash
# FlashHead 1.3B（~15GB，含 Lite 和 Pro 两个版本）
hf download Soul-AILab/SoulX-FlashHead-1_3B \
    --local-dir /opt/digital-human/SoulX-FlashHead-WEB/models/SoulX-FlashHead-1_3B

# wav2vec2 音频编码器（~1.1GB）
hf download facebook/wav2vec2-base-960h \
    --local-dir /opt/digital-human/SoulX-FlashHead-WEB/models/wav2vec2-base-960h
```

验证：
```bash
ls -lh /opt/digital-human/SoulX-FlashHead-WEB/models/SoulX-FlashHead-1_3B/
# 应有 Model_Lite/ Model_Pro/ VAE_LTX/ VAE_Wan/ 等目录
du -sh /opt/digital-human/SoulX-FlashHead-WEB/models/SoulX-FlashHead-1_3B/
# 约 15GB
```

### 4.5 V100 必要补丁

#### 补丁 1：BF16 → FP16（关键！不做会极慢）

```bash
# Pipeline 默认精度
sed -i 's/param_dtype=torch.bfloat16/param_dtype=torch.float16/' \
    /opt/digital-human/SoulX-FlashHead/flash_head/src/pipeline/flash_head_pipeline.py

# LTX VAE 默认精度
sed -i 's/dtype = torch.bfloat16/dtype = torch.float16/' \
    /opt/digital-human/SoulX-FlashHead/flash_head/ltx_video/ltx_vae.py
```

**效果对比：**

| | 修改前 (FP32 fallback) | 修改后 (FP16) |
|---|---|---|
| FPS | 9.7 | 69 |
| 推理时间 | 3.41s | 0.48s |
| 峰值显存 | 8.26 GB | 4.94 GB |

#### 补丁 2：关闭 torch.compile（防止 einops 形状错误）

```bash
sed -i 's/COMPILE_MODEL = True/COMPILE_MODEL = False/' \
    /opt/digital-human/SoulX-FlashHead/flash_head/src/pipeline/flash_head_pipeline.py
sed -i 's/COMPILE_VAE = True/COMPILE_VAE = False/' \
    /opt/digital-human/SoulX-FlashHead/flash_head/src/pipeline/flash_head_pipeline.py
```

**原因：** torch.compile 缓存特定输入形状的编译结果。音频长度不同时触发重新编译，einops 的 `rearrange` 操作报形状不匹配错误。

### 4.6 FlashHead WebSocket 服务器

OpenTalking 通过 WebSocket 二进制协议与 FlashHead 通信。需要写一个桥接服务器：

创建 `/opt/digital-human/flashhead_server.py`：

```python
"""
FlashHead WebSocket 服务器
实现 OpenTalking 的 /v1/avatar/realtime 协议
协议：客户端发 AUDI + PCM int16，服务端回 VIDX + JPEG 帧序列
"""
import asyncio, base64, json, struct, time, tempfile, os, sys
import numpy as np, torch, cv2

sys.path.insert(0, '/opt/digital-human/SoulX-FlashHead')
os.chdir('/opt/digital-human/SoulX-FlashHead')
from flash_head.inference import get_pipeline, get_base_data, get_audio_embedding, run_pipeline
import websockets

MAGIC_AUDIO = b"AUDI"
MAGIC_VIDEO = b"VIDX"
MODEL_DIR = "/opt/digital-human/SoulX-FlashHead-WEB/models/SoulX-FlashHead-1_3B"
WAV2VEC_DIR = "/opt/digital-human/SoulX-FlashHead-WEB/models/wav2vec2-base-960h"
pipeline = None

def load_pipeline():
    global pipeline
    print("[FlashHead] Loading model...")
    pipeline = get_pipeline(world_size=1, ckpt_dir=MODEL_DIR, model_type="lite", wav2vec_dir=WAV2VEC_DIR)
    print(f"[FlashHead] Model loaded, VRAM: {torch.cuda.memory_allocated()/1024**3:.2f} GB")

def pcm_to_float(pcm_bytes):
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    target = 21120  # 33 frames @ 16kHz/25fps
    if len(audio) < target:
        audio = np.pad(audio, (0, target - len(audio)))
    elif len(audio) > target:
        audio = audio[:target]
    return audio

def frames_to_jpeg_response(frames_np):
    parts = []
    for i in range(frames_np.shape[0]):
        bgr = cv2.cvtColor(frames_np[i], cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        parts.append(struct.pack('<I', len(buf)) + buf.tobytes())
    return MAGIC_VIDEO + struct.pack('<I', frames_np.shape[0]) + b''.join(parts)

async def handle_connection(websocket):
    sid = str(int(time.time() * 1000))
    ref_path = None
    print(f"[{sid}] Connected")
    try:
        async for msg in websocket:
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "session.create":
                    img_bytes = base64.b64decode(data["inputs"]["image_b64"])
                    ref_path = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
                    with open(ref_path, 'wb') as f: f.write(img_bytes)
                    get_base_data(pipeline, cond_image_path_or_dir=ref_path, base_seed=9999, use_face_crop=False)
                    await websocket.send(json.dumps({"type": "session.created", "session_id": sid,
                        "audio": {"sample_rate": 16000, "chunk_samples": 17920},
                        "video": {"fps": 25, "width": 512, "height": 512, "frame_count": 29}}))
                    print(f"[{sid}] Session created")
                elif data.get("type") == "session.close":
                    await websocket.send(json.dumps({"type": "session.closed"}))
                    break
            elif isinstance(msg, bytes) and msg[:4] == MAGIC_AUDIO:
                audio = pcm_to_float(msg[4:])
                t0 = time.time()
                emb = get_audio_embedding(pipeline, audio)
                frames = run_pipeline(pipeline, emb)
                if frames is not None:
                    arr = frames.cpu().numpy()
                    if arr.ndim == 4 and arr.shape[-1] != 3: arr = arr.transpose(0, 2, 3, 1)
                    if arr.max() <= 1.0: arr = (arr * 255).astype(np.uint8)
                    await websocket.send(frames_to_jpeg_response(arr))
                    print(f"[{sid}] {arr.shape[0]} frames in {time.time()-t0:.2f}s")
    except websockets.exceptions.ConnectionClosed: pass
    finally:
        if ref_path and os.path.exists(ref_path): os.unlink(ref_path)
        print(f"[{sid}] Disconnected")

async def main():
    load_pipeline()
    print("[FlashHead] Server started: ws://0.0.0.0:8766/v1/avatar/realtime")
    async with websockets.serve(handle_connection, "0.0.0.0", 8766, max_size=50*1024*1024):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
```

启动：
```bash
source /opt/digital-human/flashhead-env/bin/activate
export LD_LIBRARY_PATH=/opt/digital-human/flashhead-env/lib/python3.10/site-packages/nvidia/nvjitlink/lib:$LD_LIBRARY_PATH
python /opt/digital-human/flashhead_server.py
```

---

## 五、OpenTalking 部署

### 5.1 获取代码

```bash
cd /opt/digital-human
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
```

### 5.2 后端环境

```bash
# 复用 OmniRT 的 3.10 环境，或新建
python3.10 -m venv .venv310
source .venv310/bin/activate

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 5.3 前端环境

```bash
cd apps/web
npm install
```

### 5.4 配置文件

`configs/default.yaml` 关键配置：

```yaml
# 服务端口
api:
  host: 0.0.0.0
  port: 8000

# FlashHead 配置（指向本地服务器）
flashhead:
  ws_url: ws://127.0.0.1:8766/v1/avatar/realtime
  base_url: http://127.0.0.1:8766
  model: soulx-flashhead-1.3b
  fps: 25
  width: 512
  height: 512

# 默认模型选择
models:
  fasterliveportrait:
    backend: omnirt
  flashhead:
    backend: direct_ws
```

### 5.5 LLM 配置

在 `opentalking/backend/.env` 中：

```bash
# DeepSeek API（或其他 OpenAI 兼容 API）
OPEN_AI_API_KEY=你的API密钥
OPEN_AI_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# TTS
TTS_TYPE=edge
EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

### 5.6 启动后端

```bash
cd /opt/digital-human/opentalking
source .venv310/bin/activate
export LD_LIBRARY_PATH=/opt/digital-human/omnirt/.venv310/lib/python3.10/site-packages/nvidia/cuda_runtime/lib
python -m apps.unified.main
```

### 5.7 启动前端

```bash
cd /opt/digital-human/opentalking/apps/web
npx vite --port 5173 --host 0.0.0.0
```

### 5.8 WebRTC 公网 IP 修复

如果服务器在 NAT 后面（如华为云），需要在 SDP 中注入公网 IP：

找到 `adapter.py` 中的 `handle_offer` 方法（约第 334 行），在 SDP 处理中注入公网 IP：

```python
# 在 SDP answer 生成后，替换内网 IP
sdp = sdp.replace("0.0.0.0", "你的公网IP")
```

### 5.9 华为云安全组

需要开放的端口：

| 端口 | 协议 | 用途 |
|---|---|---|
| 5173 | TCP | 前端页面 |
| 8000 | TCP | 后端 API |
| 8766 | TCP | FlashHead WebSocket |
| 9000 | TCP | OmniRT |
| 40000-60000 | UDP | WebRTC 视频传输 |

---

## 六、完整启动流程

按以下顺序启动 4 个服务（每个占用一个终端）：

### 终端 1：OmniRT（FasterLivePortrait 引擎）

```bash
bash /opt/digital-human/start_omnirt_trt.sh
```

等待看到 `Application startup complete` 后继续。

### 终端 2：FlashHead 服务器

```bash
source /opt/digital-human/flashhead-env/bin/activate
export LD_LIBRARY_PATH=/opt/digital-human/flashhead-env/lib/python3.10/site-packages/nvidia/nvjitlink/lib:$LD_LIBRARY_PATH
python /opt/digital-human/flashhead_server.py
```

等待看到 `[FlashHead] Server started` 后继续。

### 终端 3：OpenTalking 后端

```bash
cd /opt/digital-human/opentalking
source .venv310/bin/activate
export LD_LIBRARY_PATH=/opt/digital-human/omnirt/.venv310/lib/python3.10/site-packages/nvidia/cuda_runtime/lib
python -m apps.unified.main
```

### 终端 4：前端

```bash
cd /opt/digital-human/opentalking/apps/web
npx vite --port 5173 --host 0.0.0.0
```

### 访问

浏览器打开 `http://服务器IP:5173`

选择模型（FasterLivePortrait 或 FlashHead），上传参考素材，开始对话。

---

## 七、录制视频（含音频）

默认录制功能只保存视频帧，不保存音频。需要打补丁。

### 7.1 修改 recording.py

文件：`opentalking/pipeline/recording/recording.py`

在 `export_flashtalk_recording` 函数前添加：

```python
import wave
import subprocess

_audio_buffers: dict[str, bytearray] = {}
_audio_sample_rates: dict[str, int] = {}

def flashtalk_recording_audio_path(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "audio.wav"

def append_flashtalk_audio(session_id: str, pcm_int16, sample_rate: int = 16000) -> None:
    pcm = np.asarray(pcm_int16, dtype=np.int16).reshape(-1)
    if session_id not in _audio_buffers:
        _audio_buffers[session_id] = bytearray()
        _audio_sample_rates[session_id] = sample_rate
    _audio_buffers[session_id].extend(pcm.tobytes())

def flush_audio_buffer(session_id: str) -> None:
    buf = _audio_buffers.pop(session_id, None)
    sr = _audio_sample_rates.pop(session_id, 16000)
    if not buf: return
    audio_path = flashtalk_recording_audio_path(session_id)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))
```

在 `export_flashtalk_recording` 函数开头添加：
```python
    flush_audio_buffer(session_id)
```

在 `export_flashtalk_recording` 函数末尾（`return output` 前）添加：
```python
    # 用 ffmpeg 合并音频
    audio_path = flashtalk_recording_audio_path(session_id)
    if audio_path.is_file():
        final = flashtalk_recording_session_dir(session_id) / "flashtalk_with_audio.mp4"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(output), "-i", str(audio_path),
                 "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)],
                capture_output=True, timeout=60)
            if final.is_file() and final.stat().st_size > 0:
                output.unlink(missing_ok=True)
                final.rename(output)
        except Exception: pass
```

### 7.2 修改 synthesis_runner.py

文件：`opentalking/pipeline/speak/synthesis_runner.py`

在 `_append_recording_frames_if_enabled` 方法后添加：

```python
    async def _append_recording_audio_if_enabled(self, pcm_int16) -> None:
        try:
            recording = await self.redis.hget(
                session_key(self.session_id),
                FLASHTALK_DISK_RECORDING_FIELD,
            )
        except Exception:
            return
        if str(recording or "").strip() != "1":
            return
        try:
            from opentalking.pipeline.recording.recording import append_flashtalk_audio
            append_flashtalk_audio(self.session_id, pcm_int16)
        except Exception:
            log.exception("Recording audio append failed: session=%s", self.session_id)
```

找到 `await self._append_recording_frames_if_enabled(frames)` 这一行，在其后添加：

```python
        await self._append_recording_audio_if_enabled(pcm_chunk)
```

**注意：** Python 的 `wave` 模块不支持 `"ab"` 追加模式，所以音频必须先缓存在内存中，导出时一次性写入。

---

## 八、两个模型对比

| | FasterLivePortrait | FlashHead |
|---|---|---|
| 原理 | 真人视频驱动 | AI 扩散模型生成 |
| 口型同步 | ✅ 精准 | ✅ 基本准确 |
| 头部运动 | ✅ 主动驱动 | ✅ 自然生成 |
| 表情 | ✅ 丰富 | ✅ 丰富 |
| 真实感 | ✅ 好（真人底板） | ⚠️ AI 生成感明显 |
| 速度 | 15-20fps（TRT） | 69fps（FP16） |
| 峰值显存 | ~10GB | ~5GB |
| 素材需求 | 需录制真人视频 | 只需一张照片 |
| 长句表现 | 有轻微卡顿 | 流畅不卡 |
| 适合场景 | 高真实感展示 | 实时对话、快速部署 |

---

## 九、V100 部署经验总结

1. **BF16 必须改 FP16**：新模型默认 BF16，V100 不支持。改两行代码，速度提升 7 倍。

2. **torch.compile 要关闭或谨慎使用**：输入形状不固定时会反复重编译并报错。

3. **TRT 只能用 8.x**：TRT 10 不支持 SM 7.0。Python 3.10 + TRT 8.6 最稳。

4. **PyTorch 用 cu124 版本**：`torch==2.5.1+cu124` 在 V100 上稳定。

5. **LD_LIBRARY_PATH 必须设置**：nvjitlink 符号冲突是 V100 常见问题。

6. **国内镜像必须配**：pip 用清华源，HuggingFace 用 hf-mirror.com。

7. **音频长度要对齐**：FlashHead 要求固定长度音频输入（21120 samples = 33 帧），不足要填充。

8. **wave 模块不支持追加**：Python 标准库 `wave` 只支持 `"w"/"wb"/"r"/"rb"`，不支持 `"ab"`。需要先内存缓存再一次性写入。

9. **WebRTC NAT 穿透**：华为云需要在 SDP 中注入公网 IP。

10. **安全组要提前开好端口**：5173、8000、8766、9000、UDP 40000-60000。

---

## 十、关键文件索引

| 文件 | 路径 | 说明 |
|---|---|---|
| OmniRT 启动脚本 | `/opt/digital-human/start_omnirt_trt.sh` | FasterLivePortrait TRT 引擎 |
| FlashHead 服务器 | `/opt/digital-human/flashhead_server.py` | WebSocket 桥接服务 |
| FlashHead 模型代码 | `/opt/digital-human/SoulX-FlashHead/` | 需要 BF16→FP16 补丁 |
| FlashHead 模型权重 | `/opt/digital-human/SoulX-FlashHead-WEB/models/` | 1.3B + wav2vec2 |
| FlashHead Python 环境 | `/opt/digital-human/flashhead-env/` | 独立 venv |
| OmniRT | `/opt/digital-human/omnirt/` | 推理引擎 |
| FasterLivePortrait | `/opt/digital-human/FasterLivePortrait/` | 模型代码 + TRT 引擎 |
| OpenTalking 后端 | `/opt/digital-human/opentalking/` | 编排 + API |
| OpenTalking 前端 | `/opt/digital-human/opentalking/apps/web/` | Vue 前端 |
| FLP 合成配置 | `opentalking/configs/synthesis/fasterliveportrait.yaml` | 运动幅度等参数 |
| FlashHead 配置 | `opentalking/configs/default.yaml` | ws_url 等 |
| 录制模块 | `opentalking/pipeline/recording/recording.py` | 需打音频补丁 |
| TRT 推理配置 | `FasterLivePortrait/configs/trt_infer.yaml` | TRT 引擎路径 |
