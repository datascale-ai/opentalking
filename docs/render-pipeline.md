# 渲染管线

## `wav2lip` / `musetalk` 路径

入口在 `SessionRunner.speak(...)`。

### 处理顺序

1. 清理中断状态与上一轮流式上下文
2. 发布 `speech.started`
3. 立即发布一条 `subtitle.chunk`
4. 构建 TTS adapter
5. TTS 逐块产出 `AudioChunk`
6. 渲染 worker 把音频块变成视频帧
7. 音频 worker 等待首帧就绪后再入 WebRTC，减少音画错位
8. 全部结束后发布 `speech.ended`

## 两个并发 worker

### 渲染 worker

它会调用:

- `render_audio_chunk_sync(...)`
- `adapter.extract_features(...)`
- `adapter.infer(...)`
- `adapter.compose_frame(...)`

并把结果送入 `WebRTCSession.video`。

### 音频 worker

它会:

- 等待首批视频帧 ready
- 把同一 `AudioChunk` 写入 `WebRTCSession.audio`
- 必要时做重采样

这样可以让首帧视频先到位，再开始音频播放。

## Wav2Lip 特殊路径

`OPENTALKING_WAV2LIP_LIVE_MODE` 支持:

- `streaming`
- `official`
- `auto`

当走 `official` 路径时，流程会变成:

1. TTS 先完整合成整段 PCM
2. 调用 `run_official_inference(...)`
3. 从生成的视频里回读全部帧
4. 一次性送入 WebRTC

这条路径延迟更高，但更接近官方推理方式。

## MuseTalk / Wav2Lip 的流式状态

为了让多 chunk 播报更平滑，`avatar_state.extra` 中会保存一些跨 chunk 状态，例如:

- 音频上下文
- overlap prediction tail
- 上一轮能量值
- 手势状态

开始新一轮播报时，`reset_avatar_speech_state(...)` 会统一重置这些状态。

## 空闲循环

`SessionRunner._idle_loop()` 会在非 speaking 状态下持续调用:

```python
adapter.idle_frame(avatar_state, frame_idx)
```

目的:

- 保持视频轨持续输出
- 避免浏览器端视频冻结

## FlashTalk 路径

入口在 `FlashTalkRunner.speak(...)`，它和普通 `SessionRunner` 不同。

### 实际链路

```text
用户文本
  -> LLM 流式输出
  -> SentenceSplitter 分句
  -> TTS
  -> 固定长度 PCM chunk
  -> FlashTalk generate
  -> WebRTC
```

特点:

- `subtitle.chunk` 会随着 LLM/TTS 过程持续更新
- FlashTalk 使用固定 chunk 大小的 16k PCM
- 支持 prebuffer、句首 opener、idle cache

## 调试导出

当设置:

```bash
export OPENTALKING_DEBUG_DUMP_SPEECH_DIR=./debug
```

普通 `SessionRunner` 会在每轮播报结束后导出:

- `tts.wav`
- `rendered_silent.mp4`
- `rendered_with_audio.mp4`
- `meta.json`

很适合定位:

- TTS 是否正常
- 首帧延迟
- 口型与音频是否对齐
