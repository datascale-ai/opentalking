# 社区

OpenTalking 以开源项目形式开发，欢迎通过 GitHub、QQ 群和文档反馈参与实时数字人编排层的
建设。

## 交流渠道

| 渠道 | 用途 |
|------|------|
| [GitHub 仓库](https://github.com/datascale-ai/opentalking) | 代码、文档、issue、pull request。 |
| [GitHub Issues](https://github.com/datascale-ai/opentalking/issues) | bug 报告、功能请求、部署问题复现。 |
| [GitHub Discussions](https://github.com/datascale-ai/opentalking/discussions) | 设计讨论、使用问答、模型接入建议。 |
| [GitHub Releases](https://github.com/datascale-ai/opentalking/releases) | 版本记录与 changelog。 |
| QQ 群 `1103327938` | 中文实时讨论，覆盖 OpenTalking、FlashTalk、OmniRT 和部署问题。 |

![AI 数字人交流群二维码](../../assets/images/qq_group_qrcode.png){ width=280 }

## 参与路径

- **报告问题**：使用 bug report 模板，附上系统、硬件、启动命令、日志和 `/models` 输出。
- **提出功能**：使用 feature request 模板，说明目标场景、期望 API、可接受的部署依赖。
- **提交文档修复**：小错别字、命令修正、案例补充都可以直接提 PR。
- **贡献模型接入**：先阅读 [模型适配器](../docs/model-adapter.md)，确认 backend 边界和验证方式。
- **参与架构讨论**：较大的 API、部署或模型策略调整建议先开 Discussion 或 Draft PR。

## 新人任务

适合首次贡献的方向：

- 补充教程中的操作截图、常见错误和环境差异。
- 为 `deployment` 页面补充权重下载镜像和校验方式。
- 为 Benchmark 页面补充可复现的结果记录。
- 改进 API 文档中的请求/响应示例。
- 增加 avatar 资产校验和案例说明。

## PR 检查清单

提交前请确认：

- 文档链接可以通过 `python -m mkdocs build --strict --clean`。
- 代码改动包含必要测试或说明为什么不需要测试。
- 新配置项同步更新教程、模型部署或 API 文档。
- PR 不包含本地私有路径、内部主机名、密钥或不可公开日志。
- 行为变更在 PR 描述中写明迁移影响。

## 反馈信息模板

部署或运行问题建议包含：

```text
OpenTalking commit:
运行方式: mock / local / direct_ws / omnirt
硬件: CPU / GPU / NPU 型号
操作系统:
Python / Node.js 版本:
启动命令:
相关 .env 配置（去掉密钥）:
/health 输出:
/models 输出:
错误日志:
```

## Roadmap

项目规划以 GitHub issue、discussion、release 和文档中的 roadmap 为准。社区页只维护参与方式，
不替代具体版本计划。
