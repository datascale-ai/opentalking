# 自定义 Avatar

自定义 Avatar 用于把自己的图片或视频素材接入 OpenTalking。当前推荐先从图片 Avatar 开始：准备成本低、验证快，也更适合在 WebUI 中快速体验。

## 你将完成什么

本页会说明：

- 什么素材适合做 Avatar。
- 图片 Avatar 和视频 Avatar 的差异。
- 如何在 WebUI 上传自定义图片 Avatar。
- 如何用脚本准备 Wav2Lip 图片或视频资产。
- 自定义 Avatar 无法显示或效果不佳时如何排查。

## Avatar 与模型兼容性

OpenTalking 正在逐步让 Avatar 与模型解耦：一个 Avatar 可以尽量被不同模型复用，但不同模型对素材仍有差异化要求。

一般可以这样理解：

- 图片 Avatar：适合快速验证，通常依赖参考图、口型检测和模型自身的驱动能力。
- 视频 Avatar：适合保留更自然的姿态和背景，但准备成本更高。
- QuickTalk：可从上传图片生成模板视频，用于快速验证形象。
- Wav2Lip：更依赖预处理后的图片或视频帧、口型 metadata 和 manifest。

如果你不确定从哪里开始，先使用 WebUI 上传图片 Avatar。

## 准备素材

### 图片

建议图片满足这些条件：

- 正脸或接近正脸，脸部清晰无遮挡。
- 光线均匀，避免强阴影、过曝和严重美颜。
- 分辨率不需要过大，默认会被限制到适合实时推理的尺寸。
- 背景尽量简洁，避免人物边缘和背景混在一起。

WebUI 上传图片时，服务端会限制文件大小并做必要缩放。当前自定义图片上传上限为 10MB。

### 视频

视频素材更适合需要保留自然动作的场景。建议：

- 人脸始终清晰可见。
- 头部运动不要过大。
- 帧率稳定，避免明显压缩伪影。
- 时长不必太长，先用短片段验证。

视频资产目前更适合通过脚本预处理后放入 Avatar 目录。

## 从图片创建 Avatar

### 在 WebUI 中上传

1. 打开 WebUI。
2. 进入形象库。
3. 点击“从本地上传新形象”。
4. 选择一个基础 Avatar。
5. 输入新 Avatar 名称并上传图片。
6. 等待处理完成后，在形象库选择新 Avatar。

![WebUI 自定义 Avatar 上传入口。](../../../assets/images/usage/webui/custom-avatar-upload.png)

*WebUI 自定义 Avatar 上传入口：点击后选择本地图片创建新形象。*

这种方式适合产品预览和快速验证。如果上传后效果不理想，优先换一张更清晰、脸部更正的图片。

### 使用脚本准备 Wav2Lip 图片资产

如果你要把图片作为内置 Wav2Lip Avatar，可以使用：

```bash
uv run python scripts/prepare_wav2lip_image_asset.py \
  --source-image ./assets/my-avatar.png \
  --out ./examples/avatars/my-avatar \
  --avatar-id my-avatar \
  --name "My Avatar"
```

生成后重启服务，WebUI 会从 Avatar 目录重新读取资产。

## 从视频创建 Avatar

使用视频脚本生成 Wav2Lip 视频 Avatar：

```bash
uv run python scripts/prepare_wav2lip_video_asset.py \
  --source-video ./assets/my-avatar.mp4 \
  --out ./examples/avatars/my-video-avatar \
  --avatar-id my-video-avatar \
  --name "My Video Avatar" \
  --max-frames 125
```

脚本会抽帧、生成预览图、写入 `manifest.json` 和口型 metadata。处理完成后，确认输出目录位于 `OPENTALKING_AVATARS_DIR` 下。

## 在 WebUI 中选择 Avatar

创建完成后：

1. 刷新 WebUI 或重启服务。
2. 在形象库中找到新 Avatar。
3. 选择模型和音色。
4. 创建会话并用短文本测试。

建议每次新增 Avatar 后先用短文本验证：

```text
你好，请用一句话介绍自己。
```

## 常见问题

### 上传失败

检查图片格式、文件大小和后端日志。图片过大、格式异常或人脸检测失败都可能导致处理失败。

### 上传成功但效果不好

优先换素材。自定义 Avatar 的效果高度依赖图片质量、脸部角度、光照和模型适配情况。

### WebUI 中看不到新 Avatar

确认 Avatar 目录位于 `OPENTALKING_AVATARS_DIR` 下，并检查 `manifest.json`、`preview.png` 是否存在。对于脚本生成的资产，通常需要重启服务或刷新页面。

### 删除后还能看到旧 Avatar

刷新页面，并确认后端实际删除了对应 Avatar 目录。只有通过 WebUI 创建的自定义 Avatar 支持在界面中删除。

## 参考：Avatar Format

一个 Avatar 目录通常包含：

- `manifest.json`：Avatar 的基础信息、模型类型和素材 metadata。
- `preview.png`：WebUI 展示用预览图。
- `reference.png`：模型使用的参考图。
- `frames/`：视频或预处理帧素材。
- `source/`：原始素材备份。

后续会在参考资料中补充更完整的 Avatar Format 说明。
