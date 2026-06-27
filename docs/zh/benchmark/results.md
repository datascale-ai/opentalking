# 结果与基线

本页只记录当前文档可引用的公开基线。新增结果时请保留完整上下文，不要只贴一个 FPS。

## 当前可引用数据

| 路径 | 硬件 / 状态 | 数据 | 说明 |
|------|-------------|------|------|
| Wav2Lip quickstart | NVIDIA 3090 路径 | `singer` 示例约 `28` 帧 / `0.83-0.85s`，约 `33 FPS` | 来自 README 的 quickstart 配置记录；用于轻量模型体验参考。 |
| FlashTalk via OmniRT | Ascend 910B2 x8，热态 full-audio | `937` 帧 / `37.377s`，约 `25 FPS` | 外部 OmniRT/模型服务推理基线，不代表 OpenTalking 本仓直接推理。 |
| FlashTalk steady chunk | Ascend 910B2 x8，热态 chunk | 29-frame chunk 约 `30 FPS` 等效 | 外部推理稳态数据，应与端到端首响分开记录。 |

## 结果模板

```markdown
### <模型> / <backend> / <硬件> / <日期>

- OpenTalking commit:
- backend commit 或服务版本:
- 硬件:
- 模型与权重:
- avatar:
- 输入音频:
- 冷启动或热态:
- `session_create_ms`:
- `llm_first_token_ms`:
- `tts_first_pcm_ms`:
- `avatar_first_frame_ms`:
- `webrtc_first_frame_ms`:
- `render_fps`:
- `av_drift_ms`:
- 备注:
```

## 解释规则

- 端到端体验优先看首响和音画同步，不能只看模型 FPS。
- 模型服务吞吐优先看 steady chunk 和队列深度，不能只看单次 cold run。
- 公开引用外部 benchmark 时必须写明来源是外部 backend。
