# OmniRT 部署

`omnirt` backend 表示 OpenTalking 不在主进程里加载 talking-head 模型，而是连接独立 OmniRT 服务。OpenTalking 负责会话、TTS 和 WebRTC；OmniRT 负责模型加载、GPU/NPU 运行时和 `/v1/audio2video/{model}`。

## 基本流程

准备两个 checkout：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/opentalking.git opentalking
git clone https://github.com/datascale-ai/omnirt.git omnirt
```

安装 OmniRT 基础环境：

```bash title="终端"
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

按模型页面准备权重后，从 OpenTalking 仓库启动对应 OmniRT quickstart 脚本，例如：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda --port 9000
```

然后启动 OpenTalking 并指向 OmniRT：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model MODEL \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8000 \
  --web-port 5173
```

`start_unified.sh --backend omnirt` 会设置 `OPENTALKING_<MODEL>_BACKEND=omnirt`、`OPENTALKING_DEFAULT_MODEL=<MODEL>` 和 `OMNIRT_ENDPOINT`。

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.backend=="omnirt")'
```

## 模型教程

- [QuickTalk with OmniRT](../quicktalk/omnirt.md)
- [Wav2Lip with OmniRT](../wav2lip/omnirt.md)
- [MuseTalk with OmniRT](../musetalk/omnirt.md)
- [FasterLivePortrait](../fasterliveportrait.md)
- [FlashTalk](../flashtalk.md)
