# Avatar 资产格式

每个头像都是 `OPENTALKING_AVATARS_DIR` 下的一个子目录，至少需要 `manifest.json`。

## 通用结构

```text
examples/avatars/<avatar_id>/
├── manifest.json
├── preview.png              # 推荐，接口 /avatars/{id}/preview 会读取它
└── ...
```

`preview.png` 目前是推荐项，不是强制项，但缺失时头像校验会给出提示。

## `manifest.json`

必填字段:

| 字段 | 说明 |
|------|------|
| `id` | 资源内部 ID |
| `model_type` | `wav2lip`、`musetalk` 或 `flashtalk` |
| `fps` | 目标帧率 |
| `sample_rate` | 目标音频采样率 |
| `width` | 输出宽度 |
| `height` | 输出高度 |
| `version` | 资源版本 |

可选字段:

| 字段 | 说明 |
|------|------|
| `name` | 展示名称 |
| `metadata` | 任意扩展元数据 |

示例:

```json
{
  "id": "demo-wav2lip",
  "name": "Demo Wav2Lip HD",
  "model_type": "wav2lip",
  "fps": 25,
  "sample_rate": 16000,
  "width": 768,
  "height": 1024,
  "version": "1.0",
  "metadata": {
    "description": "Wav2Lip debug avatar"
  }
}
```

## `wav2lip` 头像

目录要求:

```text
<avatar_id>/
├── manifest.json
├── preview.png
└── frames/
    ├── frame_00000.png
    ├── frame_00001.png
    └── ...
```

说明:

- `frames/` 是必须项
- 加载时按文件名排序
- 当前适配器既支持神经网络路径，也支持无权重时的合成嘴型回退路径

## `musetalk` 头像

最小结构:

```text
<avatar_id>/
├── manifest.json
├── preview.png
└── full_frames/
    ├── frame_00000.png
    ├── frame_00001.png
    └── ...
```

兼容目录:

- `full_frames/`
- `full_imgs/`（加载器保留兼容）

可选的预处理资产:

```text
<avatar_id>/prepared/
├── coords.pkl
├── infer_coords.pkl         # 可选，缺失时回退到 coords.pkl
├── latents.pt
├── mask/
│   ├── 00000.png
│   └── ...
└── mask_coords.pkl
```

这些文件存在时，`MuseTalkAdapter` 会优先走更完整的 prepared 资产路径。

可选手势配置:

```text
<avatar_id>/gesture_state.json
```

它可以覆盖默认手势状态、状态切换白名单、语义关键词与锚点。

## `flashtalk` 头像

最小结构:

```text
<avatar_id>/
├── manifest.json
├── preview.png
└── reference.png
```

也支持 `reference.jpg`。

可选缓存:

```text
<avatar_id>/.flashtalk_idle_cache_v*.npz
```

这是 FlashTalk idle cache。存在时可减少空闲动画预热时间。

## 校验规则

`src/opentalking/avatars/validator.py` 当前会做这些基础检查:

- 目录存在
- `manifest.json` 可解析
- `preview.png` 是否存在
- `musetalk` 是否存在 `full_frames/`
- `wav2lip` 是否存在 `frames/`

`flashtalk` 的 `reference.png` / `reference.jpg` 由运行阶段校验，不在基础校验函数里完成。
