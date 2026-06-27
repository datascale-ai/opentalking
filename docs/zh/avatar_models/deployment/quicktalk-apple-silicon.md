# QuickTalk Apple Silicon 部署

Apple Silicon 适合做配置、avatar 和前端链路验证。QuickTalk 的实时生产推理仍建议使用 CUDA 或 OmniRT；在 Mac 上优先把它当成开发模式。

## 适用场景

- 在 M 系列 Mac 上准备权重、检查 manifest、验证 WebUI 流程。
- 不方便使用 CUDA，但需要复用 QuickTalk 目录结构。
- 准备把同一套资产同步到 Linux GPU 或 OmniRT 服务。

## 权重准备

目录结构与 Linux local 模式保持一致：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/quicktalk/checkpoints

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir models/quicktalk/checkpoints
```

如果本机只做文档和资产检查，也可以跳过 CUDA 相关依赖，只确认权重目录、通用 avatar 和可选模板资源存在。

## 启动命令

优先用 `mock` 验证 API/WebUI，再切到 QuickTalk 资产检查：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra quicktalk-cpu --python 3.11

export OPENTALKING_TORCH_DEVICE=mps
export OPENTALKING_QUICKTALK_ASSET_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=0

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

如果依赖或算子不支持 MPS，请改用 `--backend mock` 验证产品流程，或把相同 `models/quicktalk/` 同步到 CUDA 机器运行。

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:8210/health
curl -s http://127.0.0.1:8210/models | jq '.statuses[] | select(.id=="quicktalk")'
```

Apple Silicon 下 `connected=false` 不一定代表资产错误，重点看 `reason` 是否指向缺依赖、缺权重或不支持的 device。

## 常见错误

| 现象 | 处理 |
|------|------|
| MPS 算子不支持 | 使用 CUDA 机器或 OmniRT 服务跑真实推理；Mac 仅保留资产验证。 |
| ONNX Runtime provider 不匹配 | 使用 `quicktalk-cpu` 依赖或切换到 Linux CUDA。 |
| 模板视频找不到 | 如果配置了固定模板视频，使用可访问的绝对路径或仓库内相对资产路径。 |
| 下载慢 | 设置 `HF_ENDPOINT`，或先在可联网机器下载后同步。 |
