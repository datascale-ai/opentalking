---
title: Persona Package
---

# Persona Package

Persona Package 是 OpenTalking 的数字人 Agent 交付包。它把形象、音色、提示词、知识库、记忆策略和运行预设组合成一个 `.otpersona` 文件，导入后可以用 `persona_id` 直接创建会话。

## 包结构

`.otpersona` 本质是 zip 包，根目录至少包含 `persona.json`：

```text
customer-support-zh.otpersona
├── persona.json
├── prompts/
│   ├── system.md
│   └── style.md
└── knowledge/
    └── docs/
        └── opentalking-product.md
```

可选目录包括 `avatar/`、`voice/`、`memory/` 和 `eval/`。v1 会保留这些目录，但主要启用提示词、知识库和会话预设。

## `persona.json`

```json
{
  "schema_version": "1.0",
  "id": "customer-support-zh",
  "name": "中文售前客服",
  "description": "面向私有化部署场景的中文产品答疑数字人 Persona。",
  "locale": "zh-CN",
  "avatar": {"id": "singer", "model": "mock"},
  "voice": {"provider": "edge", "voice_id": "zh-CN-XiaoxiaoNeural"},
  "agent": {
    "system_prompt": "prompts/system.md",
    "style_prompt": "prompts/style.md",
    "memory_enabled": true,
    "knowledge_enabled": true
  },
  "runtime": {"stt_provider": "sensevoice", "tts_provider": "edge"},
  "safety": {
    "authorized_avatar": true,
    "authorized_voice": true,
    "content_label_required": true
  }
}
```

导入包时，`knowledge/docs/` 下的文档会创建为新的知识库，并写入本地 Persona 记录。真实用户长期记忆不会被导出。

## CLI

从样板目录打包：

```bash
opentalking persona pack examples/personas/customer-support-zh --out customer-support-zh.otpersona
```

校验并导入：

```bash
opentalking persona validate customer-support-zh.otpersona
opentalking persona import customer-support-zh.otpersona
```

导出已安装 Persona：

```bash
opentalking persona export customer-support-zh --out customer-support-zh.otpersona
```

## API

- `GET /personas`：列出本地 Persona
- `GET /personas/{persona_id}`：查看详情
- `POST /personas/import`：上传 `.otpersona`
- `GET /personas/{persona_id}/export`：导出 `.otpersona`
- `DELETE /personas/{persona_id}`：删除本地 Persona 记录

创建会话时可以直接传 `persona_id`：

```json
{
  "persona_id": "customer-support-zh",
  "user_id": "client_demo"
}
```

显式传入的 `avatar_id`、`model`、`tts_provider`、`stt_provider`、`tts_voice`、`llm_system_prompt`、`knowledge_base_ids` 和 `memory_enabled` 会覆盖 Persona 默认值。
