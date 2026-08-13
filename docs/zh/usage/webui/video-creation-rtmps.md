# 视频创作边生成边发布 RTMPS：用户操作手册

本手册面向使用 OpenTalking Studio 的用户。它介绍如何选择数字人、生成口播视频，并在视频仍处于生成状态时同步发布 RTMPS，再通过 HLS 在浏览器中观看画面和声音。

核心播放链路是：

```text
视频创作 → RTMPS（H.264/AAC）→ HLS（fMP4）→ 浏览器视频播放器
```

最终 MP4 会继续保存到视频资产中。RTMPS 不需要等待 MP4 完成。

## MediaMTX 是什么

MediaMTX 可以理解为音视频的“中转站”或“媒体服务器”。它不负责生成数字人，也不负责合成口播文本；它主要负责接收一条媒体流，再提供不同的播放入口。

在本项目中，MediaMTX 的作用是：

```text
接收 RTMPS
→ 保留 H.264/AAC 音视频
→ 提供 HLS 给浏览器播放
→ 同时提供 RTSP 给验收工具读取
```

所以用户不需要让浏览器直接播放 RTMPS。视频创作页面通过 MediaMTX 把 RTMPS 转成浏览器能播放的 HLS；MediaMTX 也负责测试环境中的发布认证、读取认证和流地址管理。

## 零、从 0 开始准备

如果项目已经安装并且 `http://127.0.0.1:5280` 可以打开，可以直接跳到[打开页面](#一打开页面)。下面是新机器的最小本地测试流程。

### 0.1 准备软件

需要：

- Linux 主机；
- Python 3.10 以上，推荐 Python 3.11；
- Node.js 18 以上；
- Docker 和 Docker Compose；
- FFmpeg；
- 网络可以访问 Python/npm 依赖。

真实数字人模型还需要对应的模型权重和 GPU。第一次只想确认页面、API 和流媒体配置，可以先使用 Mock 模式。

### 0.2 获取项目并安装依赖

如果还没有项目：

```bash
export OPENTALKING_HOME="${OPENTALKING_HOME:-$HOME/opentalking}"
if [[ ! -d "$OPENTALKING_HOME/.git" ]]; then
  git clone https://github.com/datascale-ai/opentalking.git "$OPENTALKING_HOME"
fi
cd "$OPENTALKING_HOME"
```

安装后端和前端依赖：

```bash
cd "$OPENTALKING_HOME"
uv sync --extra dev --python 3.11
cp -n .env.example .env

cd apps/web
npm ci
cd ../..
```

如果系统没有 `uv`，也可以使用项目快速开始文档中的 Python venv 安装方式。真实模型依赖请按照对应模型文档安装；不要把模型权重提交到 Git。

### 0.3 配置本地流媒体测试

在 `.env` 中加入下面的本地测试配置。它只适用于本机 MediaMTX harness，不要用于生产环境：

```env
OPENTALKING_STREAMING_ENABLED=1
OPENTALKING_STREAMING_ALLOW_LOCAL_TARGETS=1
OPENTALKING_STREAMING_TEST_AUTH_BYPASS=1
OPENTALKING_STREAMING_RTMPS_CA_FILE=./outputs/streaming/tls/ca.crt
OPENTALKING_STREAMING_WHIP_CA_FILE=./outputs/streaming/tls/ca.crt
OPENTALKING_STREAMING_HLS_PROXY_URL=http://127.0.0.1:8888
```

`OPENTALKING_STREAMING_TEST_AUTH_BYPASS=1` 只用于隔离的本地测试。生产环境应关闭它，并配置正式的 `OPENTALKING_STREAMING_CONTROL_TOKEN`。

### 0.4 第一次生成 MediaMTX 凭据

凭据不从 Git 下载，也不上传到 Git。第一次在这台机器上执行：

```bash
cd "$OPENTALKING_HOME"

if [[ ! -f outputs/streaming/tls/server.crt ]]; then
  bash scripts/streaming/generate_test_pki.sh outputs/streaming/tls
fi

if [[ ! -f outputs/streaming/credentials.env || ! -f outputs/streaming/mediamtx.generated.yml ]]; then
  .venv/bin/python scripts/streaming/prepare_mediamtx_harness.py
fi

docker compose -f docker/docker-compose.streaming-test.yml up -d
```

脚本会随机生成发布密码和读取密码，保存到：

```text
$OPENTALKING_HOME/outputs/streaming/credentials.env
```

查看或复制凭据时只在受控终端或密码管理器中操作。重复测试和普通服务重启不要再次执行 `prepare_mediamtx_harness.py`，否则会轮换密码。

### 0.5 启动 OpenTalking

本地 Mock 流程使用：

```bash
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --mock --api-port 8210 --web-port 5280
```

启动脚本会构建并启动 WebUI。确认服务在线：

```bash
curl -fsS http://127.0.0.1:8210/healthz
curl -I http://127.0.0.1:5280
```

如果要使用 QuickTalk、Wav2Lip 或其他真实模型，把 `--mock` 替换为对应模型的启动命令，并先完成该模型文档中的权重和推理服务配置。

## 一、打开页面

确认 OpenTalking 服务已经启动，然后打开 Studio：

```text
本机浏览器：http://127.0.0.1:5280
远程浏览器：http://<服务器IP>:5280
```

如果浏览器和 OpenTalking 在同一台机器上，使用 `127.0.0.1:5280`。如果浏览器在另一台机器上，使用服务器 IP，例如 `http://8.92.9.220:5280`。

## 二、准备接收信息

本地测试凭据保存在：

```text
$OPENTALKING_HOME/outputs/streaming/credentials.env
```

密码只从这个文件读取，不要把密码写进文档、截图、日志或聊天消息。不要为了重复测试重新执行 `prepare_mediamtx_harness.py`，否则会轮换密码。

首次生成凭据请按上方“0.4 第一次生成 MediaMTX 凭据”执行。服务重启和重复测试不需要重新生成凭据；只有新机器首次配置、凭据泄漏或管理员明确要求轮换时，才重新执行 `prepare_mediamtx_harness.py`。轮换后要重新启动 MediaMTX，并把新值填入页面。

### 远程浏览器如何获取

如果浏览器打开的是 `http://<服务器IP>:5280`，凭据仍然在服务器的 `outputs/streaming/credentials.env` 中。请由服务器管理员通过密码管理器、受控终端或其他安全渠道把以下值交给操作者：

- `OPENTALKING_HARNESS_RTMPS_PASSWORD`：填写到 RTMPS 发布密码。
- `OPENTALKING_HARNESS_READ_PASSWORD`：组合成 `reader:<读取密码>`，填写到浏览器接收 Token。

不要通过 Git、公开聊天、日志、截图或 URL 传递这些值。项目不会提供一个返回密码的状态接口，这样可以避免密码泄漏。

### 生产环境

生产环境不使用本地 harness 生成脚本。由部署管理员在 MediaMTX、云直播平台或 Secret Manager 中创建发布/读取凭据，再通过企业密码管理流程交给有权限的操作员。代码仓库只提交配置模板和生成脚本，不提交真实密码。

视频创作页面使用下面的字段：

| 页面字段 | 本地测试填写内容 |
| --- | --- |
| RTMPS endpoint | `rtmps://127.0.0.1:1936/live` |
| Stream key | `rtmps-test` |
| 发布用户名 | `publisher` |
| 发布密码 | `credentials.env` 中的 `OPENTALKING_HARNESS_RTMPS_PASSWORD` |
| HLS 播放地址 | `/streaming/hls/live/rtmps-test/index.m3u8` |
| 浏览器接收 Token | `reader:<读取密码>`，读取密码来自 `OPENTALKING_HARNESS_READ_PASSWORD` |
| Streaming control token | 本地 test bypass 通常留空 |

注意：发布密码和浏览器接收 Token 不是同一个值。不要把发布密码填到 HLS Token，也不要把 WHIP token 填到 HLS Token。

## 三、生成并发布视频

1. 打开 Studio，点击顶部的「视频创作」。

2. 选择「离线数字人口播」。

3. 在数字人列表中选择需要的形象，例如「博士小狗」（`dogo-light2d`）。

4. 选择生成模型，并填写标题。

5. 选择音频来源：

   - 选择「口播合成」时，填写口播文本并选择 TTS 音色。
   - 如果页面提供「试听口播」，建议先试听，确认声音正常。
   - 也可以选择上传音频或使用已经复刻的音色。

6. 勾选「边生成边发布 RTMPS」。

7. 填写 RTMPS 发布信息：

   ```text
   RTMPS endpoint：rtmps://127.0.0.1:1936/live
   Stream key：rtmps-test
   发布用户名：publisher
   发布密码：从 credentials.env 读取
   ```

8. 填写浏览器预览信息：

   ```text
   HLS 播放地址：/streaming/hls/live/rtmps-test/index.m3u8
   浏览器接收 Token：reader:<读取密码>
   ```

9. 点击「生成并保存」。

点击后，系统会先创建异步视频任务和 RTMPS 任务，再开始生成第一段视频。不会等最终 MP4 完成后才开始发布。

## 四、观看画面和声音

视频创作页面出现「浏览器视频和音频预览」后，确认链路显示为：

```text
RTMPS H.264/AAC → HLS fMP4 → 浏览器播放器
```

播放器通常会自动启动。如果没有启动：

1. 点击「开始浏览器预览」。
2. 等待 HLS 状态变为「播放中（画面和声音）」。
3. 如果浏览器阻止自动播放，点击视频控件的播放按钮。
4. 检查视频控件没有处于静音状态，并把音量调高。

RTMPS 的 AAC 音频应通过 HLS 播放。不要在「流媒体」页面使用 WHEP 来验证 RTMPS 的声音；WHEP 主要用于 WHIP 的实时 H.264/Opus 链路。

## 五、如何看懂状态

页面下方会同时显示生成和发布进度：

```text
生成状态：generating  8000 ms
RTMPS：publishing     7600 ms
缓冲：400 ms
媒体帧：200 / 15
丢弃分片：0
```

各字段含义：

- 「生成状态」：视频源已经生成了多长时间。
- 「RTMPS」：已经发布了多长时间。
- 「缓冲」：尚未发布的媒体时长。
- 「媒体帧」：已发送的视频帧数 / 音频帧数。
- 「丢弃分片」：视频创作链路正常应为 `0`。

正常完成时，生成状态和 RTMPS 状态都会变成 `completed`，同时下方出现最终 MP4 预览和下载入口。

如果看到 `BrokenPipeError`，但 RTMPS 仍是 `publishing`、媒体帧继续增长、丢弃分片为 `0`，通常是 RTMPS socket 短暂断开后已经自动恢复。恢复后的新版本会清除这个旧错误。只有状态变成 `failed`，或计数长时间停止增长，才需要按故障排查。

## 六、离开页面会不会停止

不会。视频生成和 RTMPS 发布在 API 后台任务中运行，离开「视频创作」页面不会自动停止。

但是：

- 离开页面后，浏览器预览会停止或失去页面状态。
- 想停止任务时，应在页面点击「停止生成与发布」。
- 重新打开页面不会自动恢复旧页面上的播放器状态；最终 MP4 仍会保存在视频资产中。

## 七、短视频和开头缺失

HLS 需要等待第一份可播放分片。对于只有一两秒的极短口播，视频可能已经发布完成，浏览器才刚开始请求 HLS。

建议：

- 联调时先使用 8～10 秒以上的口播文本。
- HLS 地址保持默认的相对地址，不要改成 `:8888` 地址。
- 不要在视频创作过程中切换到 WHEP。
- 当前播放器会优先从 HLS 窗口较早的位置开始播放，不应主动跳到直播边缘。

## 八、常见问题

### 1. 页面提示 `streaming outputs are disabled`

说明 API 没有开启流媒体输出。联系服务启动者开启 streaming 配置并重启 API，然后刷新 Studio。

### 2. HLS 提示 Token 无效

确认浏览器接收 Token 的格式是：

```text
reader:<OPENTALKING_HARNESS_READ_PASSWORD 的值>
```

不要使用：

- RTMPS 发布密码；
- `OPENTALKING_HARNESS_WHIP_TOKEN`；
- `publisher:<密码>`；
- 带用户名密码的 HLS URL。

第一次返回 401/403 通常是 Token 错误。如果已经播放过画面后短暂出现 401/403，可能是 HLS 播放会话更新，保持任务发布状态，播放器会自动重连。

### 3. 黑屏、一直转圈或没有声音

依次检查：

1. RTMPS 状态仍为 `publishing`。
2. HLS 地址是否为 `/streaming/hls/live/rtmps-test/index.m3u8`。
3. Token 是否为 `reader:<读取密码>`。
4. 是否点击了视频控件的播放按钮。
5. 视频是否被浏览器静音。
6. 是否误用了 WHEP 接收 RTMPS。

### 4. 视频卡顿

先确认「丢弃分片」仍为 `0`，再检查：

- 浏览器和 API 是否在同一网络环境；
- 是否使用了过高的输出分辨率；
- API、MediaMTX 是否有 CPU 或网络资源不足；
- HLS 播放器是否正在显示「加载中」，而不是任务已经 failed。

联调时建议先使用 720p、25 FPS 和 8～10 秒文本，确认链路后再提高分辨率或延长视频。

### 5. 页面显示发布完成但没有实时预览

这是短视频常见现象：RTMPS 和 MP4 已经完成，HLS 播放器没有赶上可播放窗口。直接播放页面下方的最终 MP4；最终 MP4 应同时包含画面和声音。

## 九、停止服务

停止单个任务：

```text
在视频创作页面点击「停止生成与发布」
```

停止浏览器预览：

```text
点击「停止浏览器预览」
```

停止浏览器预览不会自动停止后台视频任务；如果要停止发布，必须点击「停止生成与发布」。
