---
title: Persona Package
---

# Persona Package

Persona Package is OpenTalking's portable digital-human Agent bundle. It combines avatar defaults, voice settings, prompts, knowledge documents, memory policy, and runtime presets into a `.otpersona` package that can be imported and used through `persona_id`.

## Package Layout

`.otpersona` is a zip file. The root must contain `persona.json`:

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

Optional directories include `avatar/`, `voice/`, `memory/`, and `eval/`. In v1, prompts, knowledge documents, and session presets are the primary runtime features.

## CLI

```bash
opentalking persona pack examples/personas/customer-support-zh --out customer-support-zh.otpersona
opentalking persona validate customer-support-zh.otpersona
opentalking persona import customer-support-zh.otpersona
opentalking persona export customer-support-zh --out customer-support-zh.otpersona
```

## API

- `GET /personas`
- `GET /personas/{persona_id}`
- `POST /personas/import`
- `GET /personas/{persona_id}/export`
- `DELETE /personas/{persona_id}`

Create a session with:

```json
{
  "persona_id": "customer-support-zh",
  "user_id": "client_demo"
}
```

Explicit session fields such as `avatar_id`, `model`, `tts_provider`, `stt_provider`, `tts_voice`, `llm_system_prompt`, `knowledge_base_ids`, and `memory_enabled` override Persona defaults.
