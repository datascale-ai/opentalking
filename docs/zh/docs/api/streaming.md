# 流媒体输出

OpenTalking 可以把正在运行的实时数字人会话复制到外部接收端。RTMPS 用于直播平台或 RTMP ingest，WHIP 用于 WebRTC ingest；两者只承载音视频，`speak`、`interrupt` 等控制仍通过 OpenTalking HTTP API 完成。

本功能默认关闭。启用后，所有 output API 都需要：

```text
Authorization: Bearer $OPENTALKING_STREAMING_CONTROL_TOKEN
```

本地测试 profile 可以显式设置 `OPENTALKING_STREAMING_ALLOW_LOCAL_TARGETS=1` 与测试 bypass；生产环境不要开启这两个开关。

## 启动本地接收端

仓库提供固定版本 MediaMTX harness。测试账号、短期证书和临时配置只写入被 gitignore 的 `outputs/streaming`：

```bash
cd /path/to/opentalking
bash scripts/streaming/generate_test_pki.sh outputs/streaming/tls
.venv/bin/python scripts/streaming/prepare_mediamtx_harness.py
docker compose -f docker/docker-compose.streaming-test.yml up -d
set -a; . outputs/streaming/credentials.env; set +a
```

如果沿用当前 harness 凭据，不要再次执行 `prepare_mediamtx_harness.py`；它会轮换凭据。只有需要主动轮换时才执行该脚本，并重新读取生成的 `credentials.env`。

本地 harness 使用 Linux `network_mode: host`，并把启用的 listener 全部绑定到 `127.0.0.1`。这是为了让普通 Chromium 的本地 ICE 候选直接到达 MediaMTX；它只适用于与 MediaMTX 同一台 Linux 主机上的浏览器。远程浏览器不能使用下面的 `127.0.0.1` 地址。

本地地址：

| 用途 | 地址 |
| --- | --- |
| RTMPS 发布 | `rtmps://127.0.0.1:1936/live`，stream key 为 `rtmps-test` |
| WHIP 发布 | `https://127.0.0.1:8889/whip-test/whip` |
| RTMPS 播放 | `rtsp://127.0.0.1:8554/live/rtmps-test`（读取凭据由 harness 环境变量提供） |
| WHIP 播放 | `https://127.0.0.1:8889/whip-test/whep` |

本地 WHEP 的 `8889` 端口只负责信令；浏览器实际音视频还需要 harness 映射的 `8189/udp` 和 `8190/tcp` ICE 端口。harness 只向浏览器公布 `127.0.0.1`，避免使用 Docker 容器内部地址。接收 Bearer Token 使用 `reader:<OPENTALKING_HARNESS_READ_PASSWORD>`，不要使用发布端的 `OPENTALKING_HARNESS_WHIP_TOKEN`。

MediaMTX 1.20 不会把 RTMPS 输入的 AAC 音频转码为 WebRTC 音频；`/live/rtmps-test/whep` 用于验证视频，RTMPS 的完整音视频请使用上面的 RTSP 播放地址。WHIP 输入的 `/whip-test/whep` 可验证 H.264 + Opus 音视频。

MediaMTX 的本地证书由测试 CA 签发，OpenTalking publisher 使用 `OPENTALKING_STREAMING_RTMPS_CA_FILE` 和 `OPENTALKING_STREAMING_WHIP_CA_FILE` 验证，不能把关闭 TLS 校验当作正常测试路径。

## 创建 output

先创建并启动 Session，等待 `/start` 返回 ready：

```bash
BASE=http://127.0.0.1:8210
SID=$(curl -sS -X POST "$BASE/sessions" \
  -H 'Content-Type: application/json' \
  --data '{"avatar_id":"anchor","model":"mock","tts_provider":"mock","stt_provider":"funasr"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')
curl -sS -X POST "$BASE/sessions/$SID/start"
```

RTMPS 与 WHIP 的 secret 必须使用结构化字段，不能拼进 endpoint：

```bash
curl --fail-with-body -sS -X POST "$BASE/sessions/$SID/outputs" \
  -H "Authorization: Bearer ${OPENTALKING_STREAMING_CONTROL_TOKEN:-}" \
  -H "Idempotency-Key: local-rtmps-001" \
  -H 'Content-Type: application/json' \
  --data '{
    "type":"rtmps",
    "name":"本地 RTMPS",
    "auto_connect":true,
    "transport":{
      "endpoint":"rtmps://127.0.0.1:1936/live",
      "stream_key":"rtmps-test",
      "username":"publisher",
      "password":"'"$OPENTALKING_HARNESS_RTMPS_PASSWORD"'"
    }
  }'

curl --fail-with-body -sS -X POST "$BASE/sessions/$SID/outputs" \
  -H "Authorization: Bearer ${OPENTALKING_STREAMING_CONTROL_TOKEN:-}" \
  -H "Idempotency-Key: local-whip-001" \
  -H 'Content-Type: application/json' \
  --data '{
    "type":"whip",
    "name":"本地 WHIP",
    "auto_connect":true,
    "transport":{
      "endpoint":"https://127.0.0.1:8889/whip-test/whip",
      "bearer_token":"'"$OPENTALKING_HARNESS_WHIP_TOKEN"'"
    }
  }'
```

创建返回 `201`，connect/disconnect/reconnect 返回 `202`，GET 返回不含 secret 的状态快照，删除返回 `204`。重复相同 `Idempotency-Key` 与 payload 不会重复创建 output；同 key 换 payload 会被拒绝。

```bash
curl -sS -H "Authorization: Bearer ${OPENTALKING_STREAMING_CONTROL_TOKEN:-}" \
  "$BASE/sessions/$SID/outputs"
```

## 发送和接收媒体

```bash
curl --fail-with-body -sS -X POST "$BASE/sessions/$SID/speak" \
  -H 'Content-Type: application/json' \
  --data '{"text":"欢迎来到 OpenTalking","mode":"replace","command_id":"demo-say-001","tts_provider":"mock"}'

.venv/bin/python scripts/streaming/receive_rtmps.py \
  --url "rtsp://127.0.0.1:8554/live/rtmps-test" \
  --output outputs/streaming/rtmps-capture.mp4 --seconds 30

.venv/bin/python scripts/streaming/receive_whep.py \
  --url https://127.0.0.1:8889/whip-test/whep \
  --ca-file outputs/streaming/tls/ca.crt \
  --output outputs/streaming/whip-capture.mkv \
  --stats outputs/streaming/whip-stats.json \
  --answer-sdp outputs/streaming/whip-answer.sdp --seconds 30
```

RTMPS capture 应包含 H.264 + AAC；WHEP stats 应包含视频和音频帧，并可用 answer SDP 检查 H.264 + Opus wire codec：

```bash
ffprobe -v error -show_streams -show_packets -show_frames -of json \
  outputs/streaming/rtmps-capture.mp4 > outputs/streaming/rtmps-capture.ffprobe.json
.venv/bin/python scripts/streaming/assert_media_timeline.py \
  --ffprobe-json outputs/streaming/rtmps-capture.ffprobe.json \
  --video-max-gap-ms 120 --audio-max-gap-ms 60 \
  --av-drift-p95-ms 100 --av-drift-max-ms 250
.venv/bin/python scripts/streaming/assert_whep_stats.py \
  --stats outputs/streaming/whip-stats.json \
  --sdp outputs/streaming/whip-answer.sdp
```

## Studio 流媒体页面

运行 `scripts/start_unified.sh` 后打开 WebUI 顶部的“流媒体”模块。启动实时对话后，可以在页面中创建 RTMPS/WHIP output、查看连接健康度、连接/断开/重连/删除 output，并使用浏览器 WHEP 播放器接收 MediaMTX 流。发布密码和 Bearer token 只用于请求，不会显示在 output 状态卡片或浏览器 localStorage 中；接收端 token 可留空以连接不要求鉴权的 WHEP 服务。

## 停止 harness

```bash
docker compose -f docker/docker-compose.streaming-test.yml down -v
```

接收脚本从 `OPENTALKING_HARNESS_READ_USERNAME`、`OPENTALKING_HARNESS_READ_PASSWORD` 和 `OPENTALKING_HARNESS_WHEP_TOKEN` 读取临时凭据；不要把凭据拼进 URL 或命令行。测试账号、证书私钥、capture 和 `.env` 均不得提交到 Git。
