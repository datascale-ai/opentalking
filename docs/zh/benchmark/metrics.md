# 指标定义

| 指标 | 含义 | 归属 |
|------|------|------|
| `session_create_ms` | 创建会话到 API 返回的耗时。 | OpenTalking |
| `asr_partial_latency_ms` | 用户说话到首个 partial transcript 的延迟。 | OpenTalking + STT provider |
| `llm_first_token_ms` | 文本请求到首个 LLM token 的延迟。 | OpenTalking + LLM endpoint |
| `tts_first_pcm_ms` | 句子提交到首段 PCM/音频字节返回的延迟。 | OpenTalking + TTS provider |
| `avatar_first_frame_ms` | 音频提交到首帧 avatar 视频可用的延迟。 | OpenTalking + synthesis backend |
| `render_fps` | 合成 backend 的视频帧生成吞吐。 | synthesis backend |
| `webrtc_first_frame_ms` | 浏览器收到首个可播放视频帧的时间。 | OpenTalking + WebRTC |
| `av_drift_ms` | 音频与视频播放时间线的偏移。 | OpenTalking |
| `queue_depth` | Worker 或外部模型服务队列深度。 | OpenTalking / backend |
| `steady_chunk_ms` | 稳态 chunk 推理耗时。 | synthesis backend |

## 口径约束

- 首响类指标必须说明起点和终点，例如“用户结束说话到浏览器首帧”或“API 收到文本到 TTS
  首包”。
- `render_fps` 只描述合成 backend，不等同于用户体感端到端 FPS。
- 多卡、NPU、远端模型服务需要额外记录网络拓扑和队列状态。
