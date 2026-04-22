# 硬件说明

## 按运行模式看需求

| 场景 | 推荐硬件 | 说明 |
|------|----------|------|
| 只跑 API / SSE / WebRTC 编排 | CPU | 适合接口联调 |
| `wav2lip` / `musetalk` 样例联调 | CPU 或单卡 GPU | 取决于你是否启用真实模型权重 |
| FlashTalk 远端推理 | 8 卡 GPU / NPU | 仓库脚本默认 `torchrun --nproc_per_node=8` |
| FlashTalk 本地模式 | 至少 1 张可用 GPU/NPU，生产更建议多卡 | `local` 模式由本机直接加载引擎 |

## CPU 模式

适合:

- 统一模式联调
- 头像和接口验证
- 非 FlashTalk 的轻量开发

限制:

- 实时视觉效果取决于具体模型路径
- 若没有安装 `.[models]` 或没有模型权重，更多是走回退或占位渲染路径

## CUDA

适合:

- Wav2Lip / MuseTalk 神经网络路径
- FlashTalk 本地或远端推理

建议同时准备:

- PyTorch 对应 CUDA 版本
- FFmpeg
- 足够的显存与磁盘空间

## Ascend 910B

仓库明确保留了昇腾支持入口:

- `pyproject.toml` 中的 `ascend` extra
- `docker/Dockerfile.flashtalk.ascend`
- `scripts/deploy_ascend_910b.sh`

实际部署前请先核对:

- `torch-npu`
- CANN
- 驱动与系统版本

## 存储与依赖

除了算力，通常还要准备:

- `models/` 的本地存储空间
- `examples/avatars/` 或自定义头像资产
- `voice/` 里的参考音频
- FFmpeg 可执行文件

FlashTalk 权重体积较大，部署前建议单独评估磁盘与下载时间。
