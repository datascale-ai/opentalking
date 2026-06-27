# Avatar 资产

Avatar 资产定义数字人的视觉形象。当前 OpenTalking 将 avatar 作为通用会话资产处理：
同一个 avatar 可以被不同 talking-head 模型复用，模型在启动或创建会话时按需生成自己的
缓存、模板或预处理产物。

## 最小规则

一个可用的 avatar bundle 至少应包含：

- `manifest.json`：声明 `id`、展示名、尺寸、帧率和采样率等基础信息。
- `preview.png`：用于 WebUI 形象库展示。
- 可选素材：单张参考图、抽帧结果、模板视频或模型生成的缓存。

不要把 avatar 写成 QuickTalk、MuseTalk 或 Wav2Lip 的专属资产。模型需要的派生产物
（例如 QuickTalk 模板、Wav2Lip 参考帧、MuseTalk `prepared/`）应由准备脚本、上传流程
或部署命令生成。

## 示例 manifest

```json title="examples/avatars/demo-avatar/manifest.json"
{
  "id": "demo-avatar",
  "name": "Demo Avatar",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "metadata": {}
}
```

## 准备与验证

完整 schema 和准备脚本见：

- [Avatar 资产格式](../docs/avatar-format.md)
- [模型 → Talking-head 模型](talking-head.md)

验证服务是否识别 avatar：

```bash title="终端"
curl -s http://127.0.0.1:8000/avatars | jq
```

排查时同时检查三项：会话 `model`、avatar 是否能被服务读取、`/models` 中对应 backend
是否 connected。
