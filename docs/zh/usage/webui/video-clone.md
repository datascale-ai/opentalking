# 视频克隆

“视频克隆”用于把一个固定数字人形象作为 source，再用摄像头或上传视频作为 driving input，实时驱动 source 的表情、头动和嘴部动作。

它不进入 LLM / STT / TTS 对话链路，也不会复用“实时对话”的 `speak` 队列。第一版主路径是 live camera driving；上传 driving video 用于验证一段自拍视频的驱动效果。

![视频克隆页面：source、克隆输出和 driving 设置。](../../../assets/images/usage/webui/video-clone.png)

*视频克隆页面：左侧固定 source，中间显示克隆输出，右侧配置摄像头或上传 driving video。*

## 前置条件

视频克隆依赖 FasterLivePortrait runtime。先按[FasterLivePortrait 部署文档](../../model-support/models/fasterliveportrait.md)启动 OmniRT，并确认 OpenTalking 能看到视频克隆状态。

常见检查：

```bash
curl -s http://127.0.0.1:8000/video-clone/status | jq
```

如果状态显示未连接，先检查 OmniRT endpoint、FasterLivePortrait 源码依赖和模型权重路径。

## Source 和 Driving

视频克隆里有两个容易混淆的概念：

- `source`：最终显示出来的数字人形象。它来自 OpenTalking 形象库，或来自你上传的 source 图片。
- `driving`：提供表情、头动和嘴部动作的人脸输入。它可以来自摄像头，也可以来自上传的 driving video。

摄像头本人不会变成新的数字人身份。摄像头只提供 motion signal，最终输出仍是 source 数字人。

## 页面组成

### 左侧 Source

左侧用于固定 source 形象：

- 点击已有 Avatar，可以切换被驱动的数字人。
- 点击“上传 source 形象”，可以上传本地图片作为新的 source。
- 上传 source 后，OpenTalking 会把它加入当前形象库并自动选中。

建议使用清晰正脸或半身图，避免严重遮挡、极端侧脸和过暗画面。

### 中间 Output

中间显示克隆输出。顶部提供：

- “录制输出”：把当前输出录制并保存到导出视频资产库。
- “更换形象”：返回 source 选择。
- 状态按钮：显示当前是否已停止、连接中或运行中。

底部状态会显示发送帧、接收帧、丢帧和延迟，用于判断推理是否跟得上前端采样。

### 右侧 Driving

右侧配置 driving 输入：

- “摄像头”：选择本机摄像头。
- “FPS”：控制前端采样频率。
- “分辨率”：控制发送到 runtime 的帧尺寸。
- “镜像预览”：只影响摄像头预览和发送帧方向，适合自拍视频习惯。
- “上传 driving video”：用本地视频循环作为 driving input。

如果浏览器无法打开摄像头，可以先上传 driving video 验证后端视频克隆服务。

## 操作步骤

1. 启动 FasterLivePortrait OmniRT runtime。
2. 启动 OpenTalking，并打开 WebUI。
3. 顶部切到“视频克隆”。
4. 左侧选择 source 数字人，或上传新的 source 图片。
5. 右侧选择摄像头，或上传 driving video。
6. 根据需要调整 FPS、分辨率、驱动区域和嘴部参数。
7. 点击“开始”。
8. 观察中间输出；需要保存时点击“录制输出”。
9. 点击“停止”或切换工作流，释放摄像头、WebSocket 和当前 clone session。

## 参数建议

### 拼回原图

建议默认开启。开启后会尽量把生成的人脸贴回 source 原图，保留原始构图，避免只看到放大的头部。

### 裁剪 driving 人脸

建议默认关闭。上传 driving video 时，如果画面被过度裁剪，嘴形和头部位置可能变得不自然。只有当 driving 画面里人脸太小、检测不稳定时，再尝试开启。

### 驱动区域

- “全表情”：适合完整头动和表情演示。
- “表情”：更侧重表情变化。
- “姿态”：更侧重头部姿态。
- “嘴部”：适合单独检查口型。
- “眼睛”：适合检查眨眼和眼部动作。

### 嘴部参数

“张嘴开合”可以增强或减弱嘴部幅度。“唇形重定向”可能改善嘴形闭合，但过强时容易变成单纯上下张嘴。建议小步调整，每次只改一个参数。

## 上传 driving video

上传 driving video 不会改变 source 身份。它只把视频里的脸作为 motion input。

建议 driving video：

- 人脸清晰、无遮挡。
- 不要离镜头太远。
- 不要大幅出画。
- 先使用短视频测试参数。

如果上传视频感觉嘴鼓、嘴张不开，先关闭“裁剪 driving 人脸”，再检查 driving 画面里人脸位置和尺度。

## 常见问题

### 摄像头打不开

确认页面通过 `localhost` 或 `127.0.0.1` 打开，浏览器已允许摄像头权限，且摄像头没有被其它应用占用。

### 视频克隆服务连接失败

检查 `/video-clone/status`，确认 FasterLivePortrait runtime 已启动，OpenTalking 的 OmniRT endpoint 指向正确服务。

### 嘴形只会上下张嘴

降低唇形重定向强度，或切回更完整的驱动区域。只看嘴部时可以使用“嘴部”区域，但完整演示建议使用“全表情”。

### 头部被放大

开启“拼回原图”。如果 source 图片本身脸部占比过大，可以换一张半身或构图更完整的 source。
