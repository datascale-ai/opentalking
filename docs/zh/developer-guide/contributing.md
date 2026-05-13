# 贡献指南

欢迎为 OpenTalking 提交贡献。本页说明提交变更时遵循的规范。开发环境搭建详见
[开发流程](developing.md)。

## 原则

**接口优先设计。** 新增的合成后端、语音合成 provider、语音识别 provider 或 WebRTC
实现应面向 `opentalking/core/interfaces/` 中定义的 Protocol。**不得**直接 import
`apps/` 中的具体类，否则会引入难以解除的耦合。

**Commit 按范围切分。** 适配器、路由、Worker 与前端变更应在条件允许时切分到独立
commit，便于审阅。

**代码与文档同步。** 用户可见的行为变更须在同一 PR 中同时更新 `docs/en/` 与
`docs/zh/`。配置变更须更新 `.env.example` 与 [配置](../user-guide/configuration.md)
页面。

## 提交流程

1. 对于非小型变更，先提交 issue 对方向达成一致后再开始实现。
2. 从 `main` 拉取分支，使用前缀 `feat/`、`fix/`、`docs/` 或 `refactor/` 之一。
3. 推送之前在本地运行检查：

   ```bash
   ruff check opentalking apps tests
   ruff format opentalking apps tests
   pytest tests -v
   ```

4. 尽早开 Draft PR 以便就方案获得反馈。
5. CI 通过后将 PR 标记为 ready for review。
6. 合并时 squash，除非须保留 commit 历史。

## Commit message 约定

仓库遵循 conventional commit 风格，示例：

```text
feat(worker): cache HuBERT features across sessions

Reuses extracted features between consecutive sessions on the same avatar,
reducing cold-start latency by approximately 400 ms. Keyed by avatar_id and
sample_rate.

Closes #142
```

可识别的前缀：

- `feat:` —— 新功能。
- `fix:` —— bug 修复。
- `refactor:` —— 不改变行为的重构。
- `docs:` —— 仅文档变更。
- `chore:` —— 基础设施、依赖、构建。
- `test:` —— 仅测试变更。

## 测试要求

- 新代码路径须配套测试。
- bug 修复须附带回归测试。
- 调用外部服务（DashScope、ElevenLabs 等）的测试由 `OPENTALKING_TEST_LIVE=1` 门控。
- 慢测试标记为 `@pytest.mark.slow`，默认 CI 运行时跳过。

## 文档

维护两个文档表面：

| 表面 | 更新时机 |
|------|---------|
| `README.md` / `README.en.md` | 项目级变更、功能增删、安装流程调整。 |
| `docs/` | 配置字段、API 端点、架构、部署拓扑等详细参考资料。 |

中英文版本均为一等公民。变更其一须同步另一份。

## 审阅 Pull Request

审阅时评估以下事项：

- 变更是否与已商定的 issue 或方案一致。
- 是否遵循现有项目约定（接口优先设计、commit 范围、测试）。
- 是否在同一 PR 内更新文档。
- 错误路径是否处理（网络失败、avatar 缺失、配置格式错误）。

小修正使用 GitHub suggestion 功能；实质性反馈使用 comment。

## 行为准则

社区准则见
[CODE_OF_CONDUCT.md](https://github.com/datascale-ai/opentalking/blob/main/CODE_OF_CONDUCT.md)。

## 沟通渠道

- GitHub Issues：bug 反馈与功能请求。
- QQ 群 `1103327938`：一般性讨论（参见 [社区](../about/community.md)）。
