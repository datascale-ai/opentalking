# MuseTalk

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `musetalk` |
| Backend | `omnirt`、`direct_ws` 或 `local` |
| 证据等级 | 已接入本地 adapter；local 模式会在会话初始化前运行 MuseTalk 官方预处理 |
| 推荐用途 | 需要使用 MuseTalk 质量的口型生成，且希望由 OpenTalking 统一启动的团队 |

## 推荐硬件

单 GPU 或远端模型服务。`local` 模式建议使用 CUDA GPU；首次会话前的官方预处理会额外加载 DWPose、face parsing 和 VAE。

## 权重下载

上游入口：

- [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)
- [MuseTalk on Hugging Face](https://huggingface.co/TMElyralab/MuseTalk)
- [ModelScope 搜索 MuseTalk](https://modelscope.cn/models?name=MuseTalk)
- [魔乐社区搜索 MuseTalk](https://modelers.cn/models?name=MuseTalk)

local 模式需要以下权重放在 `DIGITAL_HUMAN_HOME/models`，或通过
`OPENTALKING_MUSETALK_MODEL_ROOT` 指向等价目录：

```text
models/
  musetalk/
    musetalk.json
    pytorch_model.bin
  sd-vae-ft-mse/
    config.json
    diffusion_pytorch_model.bin
    diffusion_pytorch_model.safetensors
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

## 目录结构

`omnirt`/`direct_ws` 模式由外部服务管理 MuseTalk runtime。`local` 模式由 OpenTalking
直接加载权重，并需要 MuseTalk 官方源码用于头像预处理：

```text
DIGITAL_HUMAN_HOME/
  models/
  model-repos/
    MuseTalk/
      musetalk/utils/preprocessing.py
      musetalk/utils/blending.py
  runtimes/
    musetalk-preprocess/
      venv/bin/python
```

`runtimes/musetalk-preprocess/venv` 必须包含 full OpenMMLab 依赖，尤其是带 `mmcv._ext`
的 `mmcv`，不能只安装 `mmcv-lite`。OpenTalking 主 `.venv` 可以继续使用 `mmcv-lite` 跑
local MuseTalk 实时推理；官方预处理会自动用 `OPENTALKING_MUSETALK_PREPROCESS_PYTHON`
或上面默认路径的 Python 执行。

## 配置项

OmniRT 路径：

```yaml title="configs/default.yaml"
models:
  musetalk:
    backend: omnirt
```

local 路径：

```yaml title="configs/default.yaml"
models:
  musetalk:
    backend: local
```

## 启动命令

指向已提供 MuseTalk 的 OmniRT：

```bash title="终端"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

local 模式：

```bash title="终端"
bash scripts/start_unified.sh --backend local --model musetalk --api-port 18000 --web-port 18173 --host 0.0.0.0
```

该命令会检查本地 MuseTalk 推理依赖。用户进入对话、创建会话时，如果当前头像目录没有
`prepared/prepared_info.json` 或其中不是 `source_preprocess=musetalk_official`，OpenTalking
会先运行 MuseTalk 官方预处理，产物写到 `examples/avatars/<avatar_id>/prepared/` 或上传头像目录的
`prepared/`，然后再加载会话。

## `/models` 验证

```bash title="终端"
curl -s http://127.0.0.1:18000/models | jq '.statuses[] | select(.id=="musetalk")'
```

OmniRT 或 local runtime 可用时应返回 `connected=true`。local 模式示例：

```json
{"id":"musetalk","backend":"local","connected":true,"reason":"local_runtime"}
```

## 常见错误

| 现象 | 处理 |
|------|------|
| `reason=omnirt_unavailable` | 检查 OmniRT 是否报告 `/v1/audio2video/musetalk`。 |
| `No module named 'mmcv._ext'` | 官方预处理 Python 缺 full OpenMMLab 依赖；使用包含 full `mmcv` 的 `OPENTALKING_MUSETALK_PREPROCESS_PYTHON`。 |
| 会话创建前预处理失败 | 检查 `OPENTALKING_MUSETALK_REPO` 是否指向 MuseTalk 官方源码，且 `dwpose`、`face-parse-bisenet` 权重存在。 |
| Avatar 不匹配 | 使用 `model_type: musetalk` 的 avatar。 |
