# FlashHead

## 模型简介

FlashHead 在 OpenTalking 中主要通过外部生成式服务接入。当前 adapter 会把音频切片写成 WAV，调用 FlashHead HTTP 生成接口，再把返回的视频片段解码为帧，接入现有 WebRTC 播放链路。

它更适合片段式生成、离线导出、准实时口播，而不是极低延迟的逐帧流式推理。

## 适合场景

- 对画面质量要求较高，但可以接受片段式生成延迟。
- 希望通过 HTTP 服务接入模型，而不是 WebSocket 流式服务。
- 需要把生成结果保存为视频片段。

## 推荐 Runtime Backend

当前更推荐使用独立 FlashHead HTTP 服务，通过 `direct_ws` / adapter 方式接入。若 OmniRT 后续提供统一 FlashHead audio2video endpoint，也可以切换为 OmniRT。

## 硬件要求

硬件主要由 FlashHead 服务侧决定。OpenTalking 侧负责上传音频、读取结果和解码视频，不建议把重模型推理放进 API 进程。

## 权重与资产要求

权重在 FlashHead 服务侧准备。OpenTalking 侧需要：

- 可访问的 FlashHead base URL。
- 共享目录或可下载的输出 URL。
- Avatar 参考图。
- 输入音频切片。

## Avatar 要求

建议使用清晰的正脸参考图。FlashHead HTTP 客户端会把参考图写入共享目录，并在生成请求中传给模型服务。

## 可调整参数

### 服务连接参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_FLASHHEAD_BASE_URL` | `http://localhost:8766` | FlashHead HTTP 服务地址 |
| `OPENTALKING_FLASHHEAD_MODEL` | `soulx-flashhead-1.3b` | 服务侧模型名称 |
| `OPENTALKING_FLASHHEAD_TIMEOUT_SEC` | `600.0` | HTTP 请求超时 |

### 共享目录与输出映射

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_FLASHHEAD_SHARED_LOCAL_DIR` | `/tmp/opentalking_flashhead_io` | OpenTalking 本地共享目录 |
| `OPENTALKING_FLASHHEAD_SHARED_REMOTE_DIR` | 同 local | 模型服务看到的共享目录 |
| `OPENTALKING_FLASHHEAD_OUTPUT_LOCAL_DIR` | 空 | 输出文件本地目录映射 |
| `OPENTALKING_FLASHHEAD_OUTPUT_REMOTE_DIR` | 空 | 输出文件远端目录映射 |
| `OPENTALKING_FLASHHEAD_OUTPUT_BASE_URL` | 空 | 输出文件下载 base URL |

### 输出规格与切片参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_FLASHHEAD_FPS` | `25` | 输出 FPS |
| `OPENTALKING_FLASHHEAD_SAMPLE_RATE` | `16000` | 输入音频采样率 |
| `OPENTALKING_FLASHHEAD_WIDTH` | `416` | 输出宽度 |
| `OPENTALKING_FLASHHEAD_HEIGHT` | `704` | 输出高度 |
| `OPENTALKING_FLASHHEAD_FRAME_NUM` | `fps` | 每个生成片段帧数 |
| `OPENTALKING_FLASHHEAD_CHUNK_SAMPLES` | 自动计算 | 每个音频片段采样点数 |

### 生成配置

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_FLASHHEAD_PRESET` | `balanced` | 服务侧生成 preset |
| `OPENTALKING_FLASHHEAD_CONFIG_JSON` | 空 | 透传给 FlashHead 的 JSON 配置 |
| `OPENTALKING_FLASHHEAD_PARAMETERS_JSON` | 空 | `CONFIG_JSON` 的兼容别名 |

## OpenTalking 配置

```bash
export OPENTALKING_FLASHHEAD_BACKEND=direct_ws
export OPENTALKING_FLASHHEAD_BASE_URL=http://127.0.0.1:8766
```

如果输出文件不在本机可读，需要配置共享目录映射或输出下载地址。

## 启动与验证

1. 启动 FlashHead HTTP 服务。
2. 配置 `OPENTALKING_FLASHHEAD_BASE_URL`。
3. 启动 OpenTalking。
4. WebUI 选择 `flashhead` 模型并创建会话。

## 常见问题

### 返回结果里有视频，但 OpenTalking 读不到

配置 `OPENTALKING_FLASHHEAD_OUTPUT_LOCAL_DIR` / `OPENTALKING_FLASHHEAD_OUTPUT_REMOTE_DIR`，或提供 `OPENTALKING_FLASHHEAD_OUTPUT_BASE_URL`。

### 延迟明显高于流式模型

FlashHead 当前接入方式是片段式 HTTP 生成。降低 `frame_num`、调整 preset 或部署更强硬件可以改善等待时间，但它本质上不同于逐帧流式 WebSocket。
