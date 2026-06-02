# FasterLivePortrait

## 模型简介

FasterLivePortrait 在 OpenTalking 中通过 OmniRT 接入。当前支持两条链路：

- 实时对话：OpenTalking 生成语音，OmniRT 通过 `/v1/audio2video/fasterliveportrait` 做音频驱动数字人。
- 视频克隆：OpenTalking 固定一个数字人资产作为 `source`，浏览器摄像头或上传视频作为 `driving`，通过独立视频克隆 WebSocket 逐帧驱动表情和头动。

视频克隆不会进入 LLM、STT、TTS 对话链路。它是一个实时视觉驱动工作流，用来验证“用我的摄像头表情驱动数字人”的玩法。

## 适合场景

- 希望实时预览头像表情、头动和口型跟随效果。
- 希望把清晰正脸或半身图作为 source，再用摄像头或自拍视频做 driving。
- 希望在同一套 WebUI 中并列使用“实时对话”和“视频克隆”。

## 推荐 Runtime Backend

推荐使用 `omnirt`。OpenTalking 负责资产、WebUI、参数和浏览器帧流；OmniRT 常驻加载 FasterLivePortrait 权重并提供推理 WebSocket。

| OpenTalking 入口 | OmniRT 入口 | 用途 |
| --- | --- | --- |
| `/sessions` + FasterLivePortrait 会话 | `/v1/audio2video/fasterliveportrait` | 音频驱动实时对话 |
| `/video-clone/fasterliveportrait/ws` | `/v1/avatar/video-clone/fasterliveportrait` | 视频克隆帧流 |

## 权重与服务启动

先按 [FasterLivePortrait 模型部署](../../model-deployment/fasterliveportrait.md) 准备 FasterLivePortrait 源码、JoyVASA 权重、TensorRT/ONNXRuntime 依赖，并启动 OmniRT 与 OpenTalking。

确认 OpenTalking 能看到视频克隆服务：

```bash
curl -s http://127.0.0.1:8000/video-clone/status | jq
```

期望 `connected` 为 `true`。如果为 `false`，先检查 OmniRT 是否启动 FasterLivePortrait runtime，以及 `OMNIRT_ENDPOINT` 是否指向正确服务。

## Avatar 要求

`source` 是 OpenTalking 资产库里的数字人图片。推荐：

- 清晰正脸或半身图。
- 脸部无遮挡，光照稳定。
- 保留完整头肩构图；开启“拼回原图”后输出会贴回原始资产图，避免只看到放大的头部。

在视频克隆页可以直接上传新的 `source` 图片。上传后 OpenTalking 会复用现有 `/avatars/custom` 资产入口，把图片加入形象库并固定为当前 source。

## Driving 输入

`driving` 是驱动表情和头动的输入，不是 source：

- 摄像头实时帧是主路径。
- 上传 driving video 可用于离线或准实时验证。
- 默认不裁剪 driving 视频；如果脸部太小或检测不稳定，可尝试开启“裁剪 driving 人脸”。

## 前端参数

视频克隆页左侧提供驱动参数：

| 参数 | 作用 |
| --- | --- |
| 动作幅度 / 表情幅度 / 头动幅度 | 控制整体运动和表情强度 |
| 张嘴开合 | 上传视频嘴张不开时优先调高 |
| 驱动区域 | `全表情`、`表情`、`姿态`、`嘴部`、`眼睛` |
| 拼回原图 | 保持原 source 构图，避免输出只剩裁剪头部 |
| 相对运动 | 保留 source 与 driving 的相对运动差异 |
| 唇形归一 / 唇形重定向 | 可改善嘴部形变，但重定向过强时可能变成单纯上下张嘴 |

如果嘴部鼓或位置不对，先确认 driving video 是否被裁剪，再尝试关闭裁剪、开启拼回原图，并在“张嘴开合”和“唇形重定向”之间折中。

## 使用入口

1. 启动 OmniRT FasterLivePortrait runtime。
2. 启动 OpenTalking API 和 WebUI。
3. 打开 WebUI，顶部选择“视频克隆”。
4. 左侧选择或上传 source 形象。
5. 右侧选择摄像头，或上传 driving video。
6. 点击“开始”，在中间查看克隆输出。

停止或切换页面后，WebUI 会释放摄像头 track、WebSocket 和当前视频克隆会话。
