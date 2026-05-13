# Avatar 资产

Avatar 资产将视觉形象绑定到所选 talking-head backend。模型即使已经 connected，如果
avatar bundle 与模型不匹配，会话创建仍可能失败或效果异常。

## 最小规则

`manifest.json` 中的 `model_type` 必须与会话选择的模型兼容：

| 模型 | 典型资产要求 |
|------|--------------|
| `mock` | 只需要 preview/reference image。 |
| `wav2lip` | 参考帧或已准备的 Wav2Lip frame assets。 |
| `quicktalk` | `metadata.asset_root` 与 `metadata.template_video`。 |
| `flashhead` | FlashHead 会话使用的参考图。 |
| `flashtalk` | backend 服务兼容的人像/reference image。 |

## 示例 manifest

```json title="examples/avatars/quicktalk-demo/manifest.json"
{
  "id": "quicktalk-demo",
  "name": "QuickTalk Demo",
  "model_type": "quicktalk",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "metadata": {
    "asset_root": "/absolute/path/to/models/quicktalk/hdModule",
    "template_video": "/absolute/path/to/template.mp4"
  }
}
```

## 准备与验证

完整 schema 和准备脚本见：

- [Avatar 资产格式](../user-guide/avatar-format.md)
- [模型 → Talking-head 模型](talking-head.md)

验证服务是否识别 avatar：

```bash title="终端"
curl -s http://127.0.0.1:8000/avatars | jq
```

排查时同时检查三项：会话 `model`、avatar `model_type`、`/models` 中的 `backend`。
