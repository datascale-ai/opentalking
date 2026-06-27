# Direct WebSocket

## 适合场景

Direct WebSocket 适合已有模型服务已经提供实时音频到视频帧的 WebSocket 接口，并希望 OpenTalking 直接连接它的场景。

它通常用于：

- 接入已有 FlashTalk / MuseTalk / 自研模型服务。
- 临时联调新模型协议。
- 不希望部署 OmniRT，但又希望模型进程和 OpenTalking 解耦。

## 协议边界

OpenTalking 负责：

- 会话创建。
- Avatar 参考图或路径传递。
- 音频切片。
- WebSocket 连接、发送音频、接收帧。
- WebRTC 播放和录制。

模型服务负责：

- 加载权重。
- 按约定接收音频和 Avatar 信息。
- 返回视频帧或编码后的帧数据。

## 配置 endpoint

可以通过配置文件：

```yaml
models:
  musetalk:
    backend: direct_ws
    ws_url: ws://127.0.0.1:8765
```

或使用模型专属环境变量，例如：

```bash
export OPENTALKING_FLASHTALK_BACKEND=direct_ws
export OPENTALKING_FLASHTALK_WS_URL=ws://127.0.0.1:8765
```

FlashHead 还可以通过 HTTP base URL 方式接入：

```bash
export OPENTALKING_FLASHHEAD_BASE_URL=http://127.0.0.1:8766
```

## 请求 / 响应约定

Direct WebSocket 需要模型服务与 OpenTalking 的消息约定一致，至少包括：

- 初始化会话。
- 传递 Avatar 参考图或路径。
- 发送 PCM 音频块。
- 返回视频帧、FPS、分辨率和错误信息。
- 关闭会话。

如果协议不一致，建议优先通过 OmniRT 或单独 adapter 做一层转换。

## 验证

1. 先单独确认模型服务 WebSocket 可连接。
2. 配置 `backend: direct_ws` 和 `ws_url`。
3. 启动 OpenTalking。
4. WebUI 选择对应模型创建会话。

## 常见问题

### WebSocket 能连接但没有画面

检查模型服务是否返回了 OpenTalking 期望的帧格式、FPS 和分辨率。也要确认 Avatar 初始化是否成功。

### 连接一段时间后断开

检查 ping interval、ping timeout、模型服务超时策略和反向代理 WebSocket 配置。
