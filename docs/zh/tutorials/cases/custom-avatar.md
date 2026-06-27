# 自定义 Avatar 案例

## 目标

准备一个可被 OpenTalking 识别的自定义 avatar，并在浏览器会话中选择使用。avatar 本身是
通用形象资产；本案例使用 Wav2Lip 准备脚本生成最小可运行的参考帧派生产物。

## 前置条件

- 已完成 [Mock 端到端案例](mock-e2e.md)。
- 已阅读 [Avatar 格式](../../docs/avatar-format.md)。
- 准备一张正脸图片或一段模板视频。

## 步骤

从图片生成参考帧派生产物：

```bash title="终端"
python scripts/prepare_wav2lip_image_asset.py \
  --image /path/to/avatar.png \
  --output examples/avatars/my-avatar \
  --id my-avatar \
  --name "My Avatar" \
  --fps 25
```

从视频生成参考帧派生产物：

```bash title="终端"
python scripts/prepare_wav2lip_video_asset.py \
  --video /path/to/template.mp4 \
  --output examples/avatars/my-video-avatar \
  --id my-video-avatar \
  --name "My Video Avatar"
```

启动服务后访问 Web UI，avatar 列表会读取 `OPENTALKING_AVATARS_DIR` 指向的目录。

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/avatars | jq '.[] | select(.id=="my-avatar")'
curl -fsS http://127.0.0.1:8000/avatars/my-avatar
```

确认 `model_type` 与会话选择的模型一致。例如 Wav2Lip 资产应搭配 `wav2lip`。

## 故障排查

| 现象 | 处理方式 |
|------|----------|
| Avatar 不出现在列表 | 检查 `manifest.json` 是否存在，且 `OPENTALKING_AVATARS_DIR` 指向父目录。 |
| 会话创建失败 | 检查 `model_type` 是否与模型选择一致。 |
| 预览图不可访问 | 确认 manifest 中引用的图片或帧文件位于 avatar 目录内。 |
