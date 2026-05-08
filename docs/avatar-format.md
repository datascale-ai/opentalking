# Avatar 资产格式

## 目录布局

每个 Avatar 一个子目录，**必须**包含 `manifest.json`。

- **wav2lip**：`frames/` 下若干 `.png` / `.jpg`（按文件名排序）。
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

校验逻辑见 `opentalking.avatars.validator`。
