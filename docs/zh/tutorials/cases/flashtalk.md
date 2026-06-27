# FlashTalk 接入案例

## 目标

通过 OmniRT 接入 `flashtalk`，用于高质量 talking-head 合成。OpenTalking 只负责会话编排、
TTS、事件和 WebRTC，模型权重加载与推理由 OmniRT/模型服务承载。

## 前置条件

- 已完成 [Mock 端到端案例](mock-e2e.md)。
- 已按 [Talking-head 模型 → FlashTalk](../../../avatar_models/flashtalk.md) 准备
  SoulX-FlashTalk-14B 与 wav2vec2 相关权重。
- CUDA 路径至少准备 4090/A100 级 GPU；昇腾路径先 `source` CANN 环境。

## 步骤

CUDA 单机评估：

```bash title="终端"
cd opentalking
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

昇腾 910B 评估：

```bash title="终端"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/deploy_ascend_910b.sh
```

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashtalk")'
curl -fsS http://127.0.0.1:8000/health
```

浏览器中选择与 FlashTalk 兼容的 avatar 和 `flashtalk` 模型。若只验证编排链路，先回退到
`mock`，确认 LLM/TTS/WebRTC 正常后再排查模型服务。

## 故障排查

| 现象 | 处理方式 |
|------|----------|
| 首次启动很慢 | FlashTalk 权重大，冷启动包含依赖安装、权重加载和 worker 初始化，应查看 OmniRT 日志区分阶段。 |
| CUDA out of memory | 降低 `OPENTALKING_FLASHTALK_FRAME_NUM`、`OPENTALKING_FLASHTALK_SAMPLE_STEPS` 或输出分辨率。 |
| NPU 导入失败 | 确认已 source CANN 环境，且 `torch_npu`、驱动和 CANN 版本匹配。 |
