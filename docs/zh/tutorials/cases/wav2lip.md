# Wav2Lip 接入案例

## 目标

在 OpenTalking 中把会话模型从 `mock` 切换到 `wav2lip`。当前可直接跑通的兼容路径是
`backend: omnirt`；本地 adapter 完成后可切换为 `local`。

## 前置条件

- 已完成 [Mock 端到端案例](mock-e2e.md)。
- 已按 [Talking-head 模型 → Wav2Lip](../../model-deployment/wav2lip/local.md) 下载
  `wav2lip384.pth` 与 `s3fd.pth`。
- 已准备 OmniRT checkout，且与 `opentalking/` 位于同级目录。

## 步骤

启动 Wav2Lip OmniRT 服务：

```bash title="终端"
cd opentalking
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

配置 OpenTalking 指向 OmniRT：

```env title=".env"
OMNIRT_ENDPOINT=http://127.0.0.1:9000
```

启动 OpenTalking：

```bash title="终端"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="wav2lip")'
```

期望 `backend` 为 `omnirt` 且 `connected` 为 `true`。浏览器中选择 Wav2Lip 兼容 avatar 后
发起会话。

## 故障排查

| 现象 | 处理方式 |
|------|----------|
| `/models` 显示 `not_configured` | 检查 `OMNIRT_ENDPOINT` 是否写入当前 `.env`，并重启 OpenTalking。 |
| OmniRT 启动失败 | 查看脚本输出的日志路径，确认 Wav2Lip 与 S3FD 权重文件名和目录一致。 |
| Avatar 不匹配 | 使用 `model_type: wav2lip` 的 avatar，或用 `scripts/prepare_wav2lip_*_asset.py` 重新生成资产。 |
