# 场景案例

场景案例回答一个更实际的问题：OpenTalking 现在可以被怎样用起来。这里不重复模型部署细节，
而是把业务目标、推荐链路、配置重点、验证方式和下一步集成放在一起。

如果你刚接触项目，建议先完成 [快速上手](../tutorials/quickstart.md)，再按目标选择案例。
如果你要接入真实 talking-head 模型，先确认 [模型部署](../model-deployment/index.md) 中的
backend 与权重准备已经完成。

## 选择一个案例

<div class="grid cards" markdown>

-   :material-headset: **AI 客服数字人**

    ---

    用 `mock` 路径先跑通客服对话、TTS、字幕事件和 WebRTC，再替换成真实 Avatar backend。
    适合第一次把 OpenTalking 接入业务系统。

    [进入案例 →](customer-support.md)

-   :material-storefront: **商品讲解与直播导购**

    ---

    面向电商、展厅、课程讲解等半实时场景，重点是人设、商品资料、长文本播报和人工打断。

    [进入案例 →](product-demo-live-sales.md)

-   :material-domain: **企业私有化部署**

    ---

    OpenTalking 作为编排层，连接私有 LLM、TTS、Avatar backend、Redis 与反向代理，适合生产评估。

    [进入案例 →](private-deployment.md)

</div>

## 案例与底层教程的关系

| 你想解决的问题 | 应该看哪里 |
|----------------|------------|
| 我想知道能做哪些业务场景 | 本节场景案例 |
| 我想第一次把项目跑起来 | [快速上手](../tutorials/quickstart.md) |
| 我想部署 Wav2Lip、QuickTalk、FlashTalk | [模型部署](../model-deployment/index.md) |
| 我想知道某个接口怎么调 | [API 接口](../docs/api/index.md) |
| 我想扩展一个新的模型 backend | [模型适配器](../docs/model-adapter.md) |

## 编写新案例的模板

新增案例时建议保持同一结构，方便用户扫描：

1. 适合场景。
2. 最终效果。
3. 推荐链路。
4. 前置条件。
5. 配置与启动。
6. WebUI 或 API 操作。
7. 验证方法。
8. 常见问题。
9. 下一步扩展。

