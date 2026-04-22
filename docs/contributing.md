# 贡献指南

## 提交前建议

1. 先确认改动落在哪一层: `apps/`、`src/opentalking/`、`apps/web/`
2. 用户可见行为变化请同步更新 `README.md` 或 `docs/`
3. 新增适配器、配置项、接口时，尽量补至少一条测试

## 代码约定

- 核心协议在 `src/opentalking/core/interfaces`
- 模型注册走 `src/opentalking/models/registry.py`
- TTS 构建入口在 `src/opentalking/tts/factory.py`
- API 路由放在 `apps/api/routes`
- 统一模式与分布式模式尽量复用同一套任务协议

## 对不同类型改动的建议

### 新增模型

- 若是 `wav2lip` / `musetalk` 风格模型，优先实现 `ModelAdapter`
- 若像 FlashTalk 一样有专属推理协议，可以参考 `FlashTalkRunner` 单独接入
- 新头像格式请同步更新 [avatar-format.md](avatar-format.md)

### 新增 TTS

- 在 `src/opentalking/tts/<provider>/` 中实现
- 接入 `build_tts_adapter(...)`
- 如需前端可选项，补充 `/tts/voices` 的输出逻辑

### 新增 API

- 路由放到 `apps/api/routes`
- 如果统一模式也需要，记得同步挂到 `apps/unified/main.py`

## 验证命令

```bash
ruff check src apps tests
pytest tests apps/api/tests apps/worker/tests -v
cd apps/web && npm run typecheck
```

## 文档现状说明

仓库当前更偏向统一模式开发体验。若你在分布式 API 中新增了前端依赖的接口，也请同步更新文档，避免统一模式和分布式模式描述继续分叉。
