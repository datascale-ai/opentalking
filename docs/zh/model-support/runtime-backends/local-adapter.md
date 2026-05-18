# Local Adapter

## 适合场景

Local Adapter 表示模型在 OpenTalking 进程内加载。它适合开发调试、单机 Demo、低并发验证和模型适配开发。

当前最适合 local 的模型是 Wav2Lip 和 QuickTalk。

## 优点与限制

优点：

- 启动链路短，便于调试。
- 不需要单独维护推理服务。
- 可以直接访问本机 Avatar 和模型文件。

限制：

- API 进程会占用 GPU/CPU/内存。
- 模型依赖会影响 OpenTalking 环境。
- 多模型或多并发下隔离性较弱。

## 配置方式

通过启动脚本：

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

通过环境变量：

```bash
export OPENTALKING_QUICKTALK_BACKEND=local
export OPENTALKING_WAV2LIP_BACKEND=local
```

通过配置文件：

```yaml
models:
  quicktalk:
    backend: local
  wav2lip:
    backend: local
```

## 模型兼容性

| 模型 | local 支持建议 |
| --- | --- |
| Wav2Lip | 推荐用于本地验证 |
| QuickTalk | 推荐用于本地 GPU 验证 |
| MuseTalk | 更建议走 OmniRT |
| FlashTalk | 更建议走 OmniRT |
| FlashHead | 更建议走独立 HTTP / direct_ws |

## 验证

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
bash scripts/quickstart/status.sh
```

WebUI 中选择对应模型，使用内置 Avatar 发送短文本。

## 常见问题

### 本地模型加载失败

检查模型权重路径、安装 extras、CUDA / PyTorch / ONNX Runtime 版本，以及 `OPENTALKING_TORCH_DEVICE`。

### API 进程启动很慢

local 模式需要在进程内加载模型和预处理 Avatar。首次启动或首次选择 Avatar 时耗时较长是正常的，可以使用预热或缓存参数优化。
