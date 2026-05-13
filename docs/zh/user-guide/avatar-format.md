# Avatar 资产格式

Avatar bundle 定义数字人的视觉形象与音频对齐所需的元数据。OpenTalking 在会话创建时
读取 avatar bundle，与配置的合成模型（`wav2lip`、`musetalk`、`flashtalk`、`flashhead`、
`quicktalk`）配对，并由流式音频输入驱动视频生成。

本页说明目录结构、`manifest.json` schema、用于生成 avatar bundle 的脚本以及验证接口。

## 目录结构

每个 avatar bundle 为独立子目录，须包含 `manifest.json`：

```text
examples/avatars/
├── demo-avatar/
│   ├── manifest.json
│   └── preview.png
├── singer-wav2lip/
│   ├── manifest.json
│   ├── preview.png
│   └── frames/
│       ├── frame_00000.png
│       ├── frame_00001.png
│       └── ...
└── singer-musetalk/
    ├── manifest.json
    ├── preview.png
    └── full_frames/
        └── ...
```

各模型类型的目录约定：

| `model_type` | 必需子目录 | 内容 |
|--------------|-----------|------|
| `wav2lip` | `frames/` | 有序图像序列（PNG 或 JPG），按文件名排序。 |
| `musetalk` | `full_frames/` | 有序图像序列。后续可能扩展 `mask/` 与 `latent/`。 |
| `quicktalk` | _无_ | 通过 `metadata.asset_root` 与 `metadata.template_video` 引用外部资产。 |
| `flashtalk` | _无_ | 参考形象由模型服务端管理。 |
| `flashhead` | _无_ | 参考形象由模型服务端管理。 |

建议提供 `preview.png`；前端使用该图填充 avatar 选择器。

## `manifest.json` schema

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 全局唯一标识符，由客户端引用。 |
| `name` | string | 否 | 展示名，默认为 `id`。 |
| `model_type` | enum | 是 | 取值：`wav2lip`、`musetalk`、`quicktalk`、`flashtalk`、`flashhead`。 |
| `fps` | number | 是 | 目标输出帧率，典型值 25。 |
| `sample_rate` | number | 是 | 与 TTS 输出对齐的音频采样率，典型值 16000。 |
| `width` | number | 是 | 输出视频宽度（像素）。 |
| `height` | number | 是 | 输出视频高度（像素）。 |
| `version` | string | 否 | 资产版本字符串。 |
| `metadata` | object | 否 | 任意附加字段，按 model_type 约定使用。 |

## Wav2Lip `metadata`

wav2lip avatar 的 `metadata` 应包含嘴部定位信息：

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

坐标采用图像尺寸归一化。通过 `/avatars/custom` 上传单图 wav2lip avatar 时，OpenTalking
本地使用 MediaPipe 完成嘴部检测；检测失败时上传仍会成功但缺失 `animation` 字段，此时
OmniRT wav2lip 后端回退至内置对齐逻辑。`wav2lip_postprocess_mode` 控制服务端是否启用
后处理，默认关闭。

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

## Avatar bundle 生成

### 从视频文件生成

```bash title="终端"
python scripts/prepare_wav2lip_video_asset.py \
    --source /path/to/source.mp4 \
    --output-dir examples/avatars/my-avatar \
    --avatar-id my-avatar \
    --name "我的形象" \
    --fps 25
```

脚本执行以下步骤：

1. 调用 ffmpeg 抽帧，写入 `examples/avatars/my-avatar/frames/`。
2. 运行 MediaPipe 嘴部检测，将结果写入 `metadata.animation`。
3. 生成 `manifest.json` 与 `preview.png`。

### 从单张图片生成

```bash title="终端"
python scripts/prepare_wav2lip_image_asset.py \
    --source /path/to/face.jpg \
    --output-dir examples/avatars/my-avatar-static \
    --avatar-id my-avatar-static
```

输出单帧 `frames/frame_00000.png` 与完整 manifest。

### 交互式生成

```bash title="终端"
bash scripts/prepare-avatar.sh
```

脚本依次提示输入源文件、模型类型与 avatar 标识符。

## 验证

### REST 端点

```bash title="终端"
curl -s http://127.0.0.1:8000/avatars | jq
# [
#   {"id":"demo-avatar","name":"Demo","model_type":"mock","width":512,...},
#   ...
# ]
```

### 编程方式验证

```python
from opentalking.avatar.validator import list_avatar_dirs
from opentalking.avatar.loader import load_avatar_bundle

for path in list_avatar_dirs("./examples/avatars"):
    bundle = load_avatar_bundle(path, strict=True)
    print(bundle.manifest.id, bundle.manifest.model_type)
```

`strict=True` 在必填字段或必需子目录缺失时抛出异常，适合 CI 使用。

## 自定义上传

前端 avatar 创建流程调用 `POST /avatars/custom`，请求体为 multipart 格式：

| 字段 | 说明 |
|------|------|
| `name` | 展示名。 |
| `base_avatar_id` | 用作 manifest 模板的 avatar 标识符。 |
| `image` | 用户上传的人像图。 |

服务端复制 base avatar manifest，覆盖 `id` 与 `name`，写入
`metadata.custom_avatar=true`，将上传图保存为 `frames/frame_00000.png`，并执行嘴部
检测。

仅标记 `custom_avatar=true` 的 avatar 可通过 `DELETE /avatars/{avatar_id}` 删除。

## 源码

| 文件 | 职责 |
|------|------|
| `opentalking/avatar/loader.py` | manifest 解析与 bundle 加载。 |
| `opentalking/avatar/validator.py` | 目录遍历与严格模式校验。 |
| `opentalking/avatar/mouth_metadata.py` | MediaPipe 嘴部检测。 |
| `apps/api/routes/avatars.py` | REST 端点实现。 |
