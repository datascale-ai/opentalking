# OmniRT

OmniRT 是独立的多模型推理运行时。OpenTalking 可以通过 OmniRT 的 audio2video WebSocket 路由接入 FlashTalk、MuseTalk、Wav2Lip、QuickTalk、FasterLivePortrait 等模型；FasterLivePortrait 的视频克隆还会使用独立的 video2video 路由。

## OpenTalking 与 OmniRT 的边界

OpenTalking 负责：

- WebUI、API、会话和 TTS。
- Avatar 选择与会话编排。
- 将音频和 Avatar 信息发送给 OmniRT。
- 接收视频帧并通过 WebRTC 播放。

OmniRT 负责：

- 加载模型权重。
- 管理 GPU/NPU 推理。
- 暴露模型列表和 audio2video endpoint。
- 返回模型推理结果。

## 适合模型

| 模型 | OmniRT 建议 |
| --- | --- |
| FlashTalk | 推荐 |
| FasterLivePortrait | 推荐；支持音频驱动实时对话和视频克隆 |
| MuseTalk | 推荐 |
| QuickTalk | 推荐用于服务化部署 |
| Wav2Lip | 可用于远端推理和预加载资产 |
| FlashHead | 视 OmniRT 服务形态而定 |

## 配置 endpoint

配置统一入口：

```bash
export OPENTALKING_OMNIRT_ENDPOINT=http://127.0.0.1:9000
```

指定模型走 OmniRT：

```bash
export OPENTALKING_QUICKTALK_BACKEND=omnirt
export OPENTALKING_FLASHTALK_BACKEND=omnirt
export OPENTALKING_FASTLIVEPORTRAIT_BACKEND=omnirt
```

也可以在配置文件中写：

```yaml
omnirt_endpoint: http://127.0.0.1:9000
models:
  quicktalk:
    backend: omnirt
  flashtalk:
    backend: omnirt
  fasterliveportrait:
    backend: omnirt
```

OpenTalking 默认会按 `/v1/audio2video/{model}` 派生 WebSocket 地址。如果 OmniRT 路由不同，可以调整：

```bash
export OPENTALKING_OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE=/v1/audio2video/{model}
```

视频克隆使用 FasterLivePortrait 的视频驱动 route，通常由 WebUI 和 OpenTalking bridge 自动处理。部署时仍需确保 OmniRT 侧暴露 `/v1/video2video/fasterliveportrait`。

## 健康检查

OpenTalking 会根据 OmniRT 的模型列表判断模型是否在线。常用检查：

```bash
bash scripts/quickstart/status.sh
```

如果模型列表路径不同，可以配置：

```bash
export OPENTALKING_OMNIRT_AUDIO2VIDEO_MODELS_PATH=/v1/audio2video/models
```

## 常见问题

### 模型列表为空

确认 OmniRT 已启动、模型权重加载成功、端口可访问，并检查模型列表路径是否匹配。

### OpenTalking 连接的是旧 WebSocket 地址

当 `OMNIRT_ENDPOINT` 存在时，它优先于旧的 `*_WS_URL`。如果想使用 direct_ws，请把对应模型后端改成 `direct_ws`。

### 首次请求很慢

首次请求可能包含模型加载、Avatar 预处理和缓存构建。Wav2Lip 可通过 `OPENTALKING_WAV2LIP_PRELOAD` 在 unified 启动时预加载部分资产。
