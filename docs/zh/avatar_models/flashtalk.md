# FlashTalk

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `flashtalk` |
| Backend | `omnirt`，legacy `direct_ws` fallback |
| 证据等级 | OmniRT 路径已文档化，Ascend 路径已有验证记录 |
| 推荐用途 | 高质量私有化、重模型、多卡 GPU/NPU |

## 推荐硬件

CUDA 评估建议 4090/A100 级 GPU；Ascend 910B 路径建议在宿主机 CANN 环境下部署。

## 权重下载

Hugging Face 主源：

- [Soul-AILab/SoulX-FlashTalk-14B](https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B)
- [TencentGameMate/chinese-wav2vec2-base](https://huggingface.co/TencentGameMate/chinese-wav2vec2-base)

```bash title="终端"
hf download Soul-AILab/SoulX-FlashTalk-14B --local-dir "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B"
hf download TencentGameMate/chinese-wav2vec2-base --local-dir "$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base"
```

国内可搜索 ModelScope 或魔乐社区的 `SoulX-FlashTalk-14B` 与 `chinese-wav2vec2-base`。

## 目录结构

```text
$OMNIRT_MODEL_ROOT/
├── SoulX-FlashTalk-14B/
├── chinese-wav2vec2-base/
└── SoulX-FlashTalk/        # 可选，自定义 CUDA 手动路径
```

## 配置项

```yaml title="configs/default.yaml"
models:
  flashtalk:
    backend: omnirt
```

Legacy WebSocket fallback：

```env title=".env"
OPENTALKING_FLASHTALK_WS_URL=ws://127.0.0.1:8765
```

## 启动命令

CUDA：

```bash title="终端"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

Ascend：

```bash title="终端"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu --nproc 8
```

## `/models` 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashtalk")'
```

期望：

```json
{"id":"flashtalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```

## 常见错误

| 现象 | 处理 |
|------|------|
| 冷启动很慢 | 查看 OmniRT/FlashTalk 日志，区分依赖安装、权重加载和 worker 初始化。 |
| CUDA OOM | 降低 `OPENTALKING_FLASHTALK_FRAME_NUM`、`OPENTALKING_FLASHTALK_SAMPLE_STEPS` 或分辨率。 |
| NPU import 失败 | 确认已 source CANN，且 `torch_npu`、驱动和 CANN 版本匹配。 |
| `reason=not_configured` | 配置 `OMNIRT_ENDPOINT` 或用 `start_all.sh --omnirt ...`。 |
