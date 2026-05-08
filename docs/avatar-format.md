# Avatar 资产格式

## 目录布局

每个 Avatar 一个子目录，**必须**包含 `manifest.json`。

- **wav2lip**：`frames/` 下若干 `.png` / `.jpg`（按文件名排序）。单图上传资产会写入 `frames/frame_00000.png`，并把嘴部定位信息写入 `manifest.json` 的 `metadata.animation`。
- **musetalk**：`full_frames/` 下同样为有序图像序列（完整帧；后续可扩展 mask、latent 等子目录）。
- **quicktalk**：使用 `metadata.asset_root` 指向模型资产目录，并用 `metadata.template_video` 指向模板视频。

推荐提供 `preview.png` 供前端展示。

## manifest.json 字段

| 字段 | 说明 |
|------|------|
| `id` | 唯一 ID |
| `name` | 展示名（可选） |
| `model_type` | `wav2lip`、`musetalk`、`quicktalk`、`flashtalk` 或 `flashhead` |
| `fps` | 目标帧率 |
| `sample_rate` | 音频采样率（与 TTS 输出对齐，常用 16000） |
| `width` / `height` | 视频分辨率 |
| `version` | 资产版本字符串 |
| `metadata` | 任意附加信息；`quicktalk` 需要 `asset_root` 和 `template_video` |

## QuickTalk manifest 示例

```json
{
  "id": "quicktalk-daytime",
  "name": "QuickTalk Daytime",
  "model_type": "quicktalk",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "version": "1.0",
  "metadata": {
    "asset_root": "/path/to/quicktalk/assets",
    "template_video": "/path/to/template.mp4"
  }
}
```

### Wav2Lip metadata

Wav2Lip 资产的 `metadata` 推荐包含：

```json
{
  "source_image_hash": "<sha256>",
  "animation": {
    "mouth_center": [0.5, 0.56],
    "mouth_rx": 0.06,
    "mouth_ry": 0.02,
    "outer_lip": [[0.45, 0.55], [0.5, 0.53], [0.55, 0.55]],
    "inner_mouth": [[0.47, 0.55], [0.53, 0.55], [0.5, 0.57]]
  }
}
```

坐标均为相对图片宽高归一化后的比例值。OpenTalking 在 `/avatars/custom` 上传 Wav2Lip 自定义形象时会本地运行可选 MediaPipe 检测；如果检测失败，上传仍会成功，但不会写入 `animation`。OmniRT 的 Wav2Lip 服务可读取这段 metadata，并通过服务侧启动配置 `wav2lip_postprocess_mode` 决定是否启用指定 Wav2Lip 后处理模式；默认关闭时保持原生 Wav2Lip 输出。

校验逻辑见 `opentalking.avatar.validator`。
