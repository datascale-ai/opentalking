# 视频生成过程中分片发布 RTMPS：执行文档

> 文档状态：已实现，可直接执行。本文对应当前分支的分片生成、异步 VideoCreationJob、独立 RTMPS job API 和 Studio 前端。
>
> 重要：本链路的 WebUI 端口是 `5280`，API 端口是 `8210`；`5180` 不属于本测试配置。密码/token 不写入本文，按第 3 节从本机 `credentials.env` 读取。

## 1. 目标和边界

目标不是把已经生成好的 MP4 再推到 RTMPS，而是让视频生成器在产生媒体帧时就把数据送入一条持续的 RTMPS 连接：

```text
音频/TTS
   ↓
VideoCreationJob（后台生成）
   ├─ MediaChunk / ChunkQueue ──> ChunkedRTMPSPublisher ──> RTMPS ingest
   └─ MP4 writer + mux ─────────> 最终 MP4 export（并行归档）
```

必须满足：

- 不等待 `result.mp4` 完全写完才开始 RTMPS。
- 一个视频任务只建立一条 RTMPS 连接，依次发送 chunk 1、chunk 2、chunk 3；最终 MP4/export 成功后才发送 EOF 并关闭。
- 第一段必须包含可解码的 H.264 IDR、SPS/PPS 和 AAC 配置。
- 后续分片的 PTS 单调递增，不能因为分片边界重置时间戳。
- 生成速度过快时使用有界缓冲和背压；离线视频不能像实时会话 output 一样静默丢帧。
- RTMPS 首帧到达时间必须早于最终 MP4 完成时间：`t_first_rtmps < t_final_mp4`。
- 最终 MP4 是归档结果，不是 RTMPS 的输入文件。

### 1.1 必须区分的四条链路

| 链路 | 输入 | 用途 | 是否属于本方案 |
| --- | --- | --- | --- |
| WHIP/WHEP | 实时 Session 的 H.264/Opus | 浏览器接收实时数字人 | 否，继续保留 |
| 现有 Session RTMPS | 实时 Session 的 Program 音视频 | 直播/实时推流 | 否，不能当成离线视频推流 |
| 视频创作分片 RTMPS → HLS | `VideoCreationJob` 逐段产生的 H.264/AAC | 边生成边发布，并在浏览器播放完整音视频 | 是，新链路 |
| 最终 MP4 | 完整视频文件 | 下载、归档、再次处理 | 是并行产物，不是推流前置条件 |

因此，Studio 中看到的“RTMPS 已连接”只能说明实时 Session 的 RTMPS publisher 已完成握手，不能说明视频创作分片已经开始发布。新链路必须有独立的 `rtmps_job_id`、生成进度和发布进度。

## 2. 验收时间线

每次验收都记录下列时间点：

| 时间点 | 含义 | 产生位置 |
| --- | --- | --- |
| `t0` | 创建视频任务 | `POST /video-creation/jobs` |
| `t1` | 第一段视频/音频进入 `ChunkQueue` | `VideoCreationService` |
| `t2` | RTMPS 接收端收到第一帧 | MediaMTX/RTSP capture |
| `t3` | 最终 MP4 export 创建完成 | `VideoCreationJobManager` |
| `t4` | 发布器收到 EOF 并正常关闭连接 | `ChunkedRTMPSPublisher` |

硬性条件：

```text
t2 < t3
```

`t4` 是 publisher 收到 EOF、flush 并关闭 RTMPS 的时间。当前实现只有在最终 MP4 mux 和 export 注册成功后才发送 EOF，因此正常情况下 `t4 >= t3`。如果 mux/export 失败，ChunkHub 发送 `video_export_failed`，publisher 必须进入 `failed`，不能把已经发送的媒体误报成正常 completed。如果 `t2` 只在 `t3` 之后出现，说明实现仍然在等待完整 MP4；即使 Studio 显示 `connected/healthy`，也不能判定本需求通过。

## 3. 当前本地测试环境

以下命令用于准备现有 MediaMTX harness。首次创建 harness 或明确要轮换凭据时才执行生成命令；普通服务重启、机器重启、重复测试都不要重新执行 `prepare_mediamtx_harness.py`，因为它会轮换发布密码和读取密码。

```bash
export OPENTALKING_HOME="${OPENTALKING_HOME:-$HOME/opentalking}"
cd "$OPENTALKING_HOME"

# 首次配置时执行；文件已存在时跳过。
if [[ ! -f outputs/streaming/tls/server.crt ]]; then
  bash scripts/streaming/generate_test_pki.sh outputs/streaming/tls
fi
if [[ ! -f outputs/streaming/credentials.env || ! -f outputs/streaming/mediamtx.generated.yml ]]; then
  .venv/bin/python scripts/streaming/prepare_mediamtx_harness.py
fi

# 凭据只进入当前 shell 环境，不写入代码或日志。
set -a
. outputs/streaming/credentials.env
set +a

docker compose -f docker/docker-compose.streaming-test.yml up -d
docker compose -f docker/docker-compose.streaming-test.yml ps
```

API/WebUI 的启动和端口检查见第 7.1 节；如果服务还没启动，此处不应提前执行 `curl 8210/5280`。

如果浏览器在另一台机器上，第一次生成 harness 前先设置服务器公网地址，例如：

```bash
export OPENTALKING_STREAMING_PUBLIC_IP=<服务器公网IP>
.venv/bin/python scripts/streaming/prepare_mediamtx_harness.py
```

这会让 MediaMTX 为远程 WHEP 浏览器公布公网 ICE 地址，同时会轮换凭据；执行后必须重新加载 `outputs/streaming/credentials.env` 并重启 MediaMTX。浏览器 HLS 通过 WebUI 同源代理访问，远程浏览器只需访问服务器的 `5280/tcp`；`8888/tcp` 仅用于服务器内的 MediaMTX 或直接诊断。已经存在的 loopback harness 不要仅因为服务器重启就重新生成。

当前 harness 的固定字段如下。密码和 token 必须从 `credentials.env` 读取，本文不复制实际 secret：

| 字段 | 测试值/来源 | 用途 |
| --- | --- | --- |
| RTMPS 发布 endpoint | `rtmps://127.0.0.1:1936/live` | 后端 publisher 连接地址 |
| RTMPS 发布 stream key | `rtmps-test` | 拼到 endpoint path 后面 |
| RTMPS 发布 username | `$OPENTALKING_HARNESS_RTMPS_USERNAME`，当前为 `publisher` | MediaMTX 发布认证 |
| RTMPS 发布 password | `$OPENTALKING_HARNESS_RTMPS_PASSWORD` | MediaMTX 发布认证 |
| WHIP 发布 token | `$OPENTALKING_HARNESS_WHIP_TOKEN` | 只用于实时 WHIP，不用于 RTMPS |
| RTSP 接收 username | `$OPENTALKING_HARNESS_READ_USERNAME`，当前为 `reader` | 验收 RTMPS 转入流 |
| RTSP 接收 password | `$OPENTALKING_HARNESS_READ_PASSWORD` | 验收 RTMPS 转入流 |
| 浏览器 HLS 接收 Token | `$OPENTALKING_HARNESS_WHEP_TOKEN`，格式 `reader:<读取密码>` | HLS playlist/segment 的 Basic Auth；只在浏览器内存使用 |
| WHEP 接收 Bearer | `$OPENTALKING_HARNESS_WHEP_TOKEN`，格式 `reader:<读取密码>` | 只用于 WHIP/WHEP 链路 |

### 3.1 RTMPS、HLS 和 WHEP 的凭据不能混用

视频创作分片 RTMPS 的发送端只填写：

```text
endpoint:   rtmps://127.0.0.1:1936/live
stream_key: rtmps-test
username:   publisher
password:   OPENTALKING_HARNESS_RTMPS_PASSWORD 的值
```

接收端如果验证 RTMPS 转入流，使用 RTSP：

```text
rtsp://127.0.0.1:8554/live/rtmps-test
username: reader
password: OPENTALKING_HARNESS_READ_PASSWORD 的值
```

`OPENTALKING_HARNESS_WHIP_TOKEN` 是 WHIP 发布 token，不是 RTMPS password，也不是浏览器 HLS reader token。当前 MediaMTX 1.20 对 RTMPS 输入执行 RTMPS→WHEP 时不会把 AAC 自动转换成 WebRTC Opus，因此 RTMPS 浏览器播放统一使用 HLS；HLS 保留 H.264/AAC，WHEP 只用于 WHIP 的 H.264/Opus。

浏览器 HLS 播放地址（同源代理，不要在前端填 `:8888`）：

```text
/streaming/hls/live/rtmps-test/index.m3u8
```

本机完整地址是 `http://127.0.0.1:5280/streaming/hls/live/rtmps-test/index.m3u8`；远程完整地址是 `http://<服务器公网IP>:5280/streaming/hls/live/rtmps-test/index.m3u8`。API 代理在服务器内部访问 MediaMTX，并处理 HLS 的 cookie-check 重定向，因此浏览器不需要直接访问 `8888`。

浏览器播放器会把 `reader:<读取密码>` 编码为 HTTP Basic Authorization 请求头，不要把用户名密码拼到 HLS URL，也不要保存到 localStorage。

## 4. 数据模型和不变量

### 4.1 `MediaChunk`

实现位于 `opentalking/streaming/chunks.py`，当前字段如下：

```python
@dataclass(frozen=True, slots=True)
class MediaChunk:
    sequence: int
    start_pts_ms: float
    end_pts_ms: float
    video: tuple[ProgramVideo, ...] = ()
    audio: tuple[ProgramAudio, ...] = ()
    starts_with_keyframe: bool = False
    is_final: bool = False
```

视频和音频使用项目内部的 `ProgramVideo`/`ProgramAudio` wrapper，publisher 在输出阶段再转换为 PyAV/FFmpeg 帧。必须保留：

- `sequence`：从 0 或 1 开始，整个 job 内严格递增。
- `start_pts_ms`、`end_pts_ms`：使用统一媒体时钟，不随 chunk 重置。
- 视频帧的 `pts`、`time_base`。
- 音频帧的 `pts`、`time_base`、sample rate 和 channel layout。
- `starts_with_keyframe`：第一段和重连恢复段必须为真。
- `is_final`：只由生产者在所有媒体发送完后设置。

### 4.2 `ChunkQueue`

队列建议满足：

```text
producer: await queue.put(chunk)  # 只占用媒体容量
consumer: chunk = await queue.get()
finish:   await queue.finish()    # 终止标记不占媒体容量
fail:     await queue.fail(code)  # 终止标记不占媒体容量
```

禁止使用现有实时 `RTMPSPublisher` 的“满队列丢最旧帧”策略。视频创作是有限长度的离线任务，默认规则应为：

- 队列达到上限时阻塞生产者，形成背压。
- `max_chunks` 只限制媒体分片；EOF/失败标记使用独立的终止槽位。因此，
  即使历史分片刚好填满队列，源任务仍可以完成关闭，publisher 也不会永久等不到 EOF。
- 只有明确配置了“允许丢帧”的实时模式才允许 drop；视频创作分片默认 `dropped_chunks == 0`。
- 记录 `queue_depth`、`buffer_duration_ms`、`blocked_ms` 和 `dropped_chunks`。
- `finish()`、`fail()` 和 `unsubscribe()` 必须可唤醒消费者/生产者，不能让 publisher 或
  `VideoCreationJob` 永久等待。
- publisher 失败、停止或重连替换订阅时，manager 必须在 watcher 的 `finally` 中退订旧
  `ChunkQueue`。退订会关闭队列并唤醒正在等待的 `put()`，所以 RTMPS 断线不会反向停止
  `VideoCreationJob` 或最终 MP4 归档。
- producer 异常时发送带错误信息的终止事件，publisher 不能把异常误判成正常 EOF。

推荐默认值：

```text
chunk_duration_ms = 500
queue_max_chunks = 16
minimum_replay_gop = 1
gop_seconds = 1
video_fps = 25
audio_sample_rate = 48000
```

### 4.3 编码和时间戳

RTMPS 输出使用 FLV 封装，媒体编码固定为：

```text
video: H.264 / yuv420p / no B-frame
audio: AAC / 48 kHz / mono 或 stereo（按输入配置）
```

第一片必须完成：

1. 打开 RTMPS 连接和 FLV muxer。
2. 建立 H.264 和 AAC stream。
3. 编码包含 SPS/PPS 的 IDR。
4. 写入 AAC sequence/config packet。
5. 再写普通 P 帧和音频帧。

每个媒体类型的 PTS 必须严格单调。视频 PTS 使用 `1/fps` time base，音频 PTS 使用 `1/sample_rate` time base；不要使用“每片从 0 开始”的相对时间戳。视频和音频的相对漂移验收目标为 P95 ≤ 100 ms、最大 ≤ 250 ms。

## 5. 分阶段实施步骤

### 阶段 A：分片基础设施（已实现）

实现文件为 `opentalking/streaming/chunks.py`：

1. 实现 `MediaChunk`、`ChunkEOF`、`ChunkFailure`。
2. `VideoCreationChunkSink` 使用 `publish(chunk)`、`finish()`、`fail(code, detail)`。
3. 实现有界 `ChunkQueue`，提供 `depth`、`buffer_duration_ms`、`closed` 等只读指标。
4. 增加单元测试：空队列阻塞、满队列背压、EOF 唤醒、producer 异常传播、sequence 和 PTS 校验。

测试文件：

```text
tests/unit/test_media_chunks.py
```

验收命令：

```bash
.venv/bin/pytest tests/unit/test_media_chunks.py -q
```

### 阶段 B：独立的 `ChunkedRTMPSPublisher`（已实现）

新增 `opentalking/streaming/destinations/rtmps_chunked.py`，不要把它直接塞进现有实时 `RTMPSPublisher`。

#### B.1 连接生命周期

```text
created
  → connecting
  → publishing
  → finalizing
  → completed
```

异常路径：

```text
publishing --BrokenPipeError/连接断开--> reconnecting
reconnecting --成功--> publishing
reconnecting --超过重试次数--> failed
```

要求：

1. 复用现有 `RTMPSSettings`、endpoint 校验、SSRF/CIDR 校验、TLS CA 校验和 stream key 校验。
2. 只在 publisher 内部构造带 username/password 的 RTMPS URL；日志、状态接口、Redis snapshot 都不得包含 secret。
3. 连接成功后持续消费同一队列，不得按 chunk 重连。
4. 使用 `time.monotonic()` 按媒体 PTS pacing；生成速度快时最多提前一个配置的 buffer，不能一次性瞬间推完整个视频。
5. `await container.close()` 后才允许把状态置为 `completed`。
6. 正常 EOF 必须 flush video/audio encoder，再 flush FLV muxer，然后关闭 RTMPS socket。

#### B.2 断线和 `BrokenPipeError`

`BrokenPipeError` 不是“已连接但完成”的状态。处理流程：

1. 记录错误类型和断开时间，不记录异常文本中的 URL、密码或上游响应 body。
2. 保留最近一个完整 GOP 的 chunk，至少包含一个 IDR 和对应音频。
3. 关闭旧 container，按 250 ms、500 ms、1 s、2 s……指数退避重连，受 `reconnect_max_delay_sec` 限制。
4. 重连后从最近的关键帧 chunk 开始恢复；恢复片必须重新写 SPS/PPS 和 AAC config。
5. 连接中断期间生产者继续受队列背压；不能静默丢掉尚未发布的离线媒体。
6. 若重连次数耗尽，状态为 `failed`，并让视频任务得到明确失败原因；不能报告 `healthy`。

这里的“无丢帧”指 publisher 处理能力范围内不主动 drop。网络断开期间如果内存队列即将耗尽，应暂停生成而不是无限增长；如果超过磁盘/内存预算，应进入 `failed` 并保留可诊断的 `backpressure_timeout`。

对应测试文件：

```text
tests/unit/test_rtmps_chunked_publisher.py
```

### 阶段 C：`VideoCreationService` 分片接入（已实现）

给以下方法增加可选参数：

```python
chunk_sink: VideoCreationChunkSink | None = None
```

需要覆盖：

```text
create_from_audio_file()
create_from_tts_text()
create_reference_video()
create_from_duo_dialog()
_create_from_pcm()
```

#### C.1 通用模型路径

启用 `chunk_sink` 时，代码不再等待完整 `frames` 列表，而是按下面路径同时写归档文件和发布队列：

```text
client.generate(audio_chunk)
  → 逐帧应用 composition
  → 编码为 MediaChunk
       ├─ await chunk_sink.publish(chunk)
       └─ 写入归档 video writer
```

归档使用增量 writer；RTMPS 使用有界 `ChunkQueue`，只保留配置的重连 GOP、编码器缓冲和最终 MP4 的必要临时状态。

#### C.2 Light2D 路径

当前 Light2D 路径已经使用可复用的组合帧迭代器：

```text
renderer.iter_frames()
  → composition
  → archive writer
  → chunk assembler
  → chunk_sink.publish()
```

归档 writer 和 RTMPS publisher 必须消费同一顺序的帧，不能各自重新渲染一次，否则容易出现 MP4 与 RTMPS 画面不一致、GPU 负载翻倍和 PTS 漂移。

#### C.3 音频策略

第一版可以保留现有“先得到完整 PCM”的输入流程，但不能等待完整 MP4：得到音频后，视频生成每产生一个 chunk 就把对应音频片段放入同一个 `MediaChunk`。这会消除“等待 MP4 完成”的主要延迟。

若要进一步降低 TTS 首帧延迟，第二阶段再把 `_synthesize_tts_pcm()` 改为 TTS chunk 直接驱动视频生成；这属于“音频生成也流式化”，不能和本次“MP4 不再作为 RTMPS 前置条件”混为一谈。

#### C.4 结束顺序

生成任务必须遵守以下顺序：

```text
所有视频帧已生成
→ 所有音频尾帧已入队
→ emitter.flush()（只发送最后一片，不发送 EOF）
→ 关闭 archive writer
→ mux 完整 MP4
→ create_video_export()
→ ChunkQueue.finish()（发送 EOF）
→ publisher flush encoder/muxer 并关闭 RTMPS
→ job 状态 completed，并填 final_export_id
```

为了满足 `t2 < t3`，媒体 chunk 发布不得等待 MP4 export 创建；最终 MP4 只能在所有媒体帧已经进入 chunk pipeline 后做归档 mux。EOF 是成功完成信号，不是“最后一片已生成”信号：mux/export 任一步失败时发送 `ChunkFailure(video_export_failed)`，不能发送正常 EOF。

### 阶段 D：异步 `VideoCreationJobManager`（已实现）

`POST /video-creation/jobs` 在 `execution_mode=async` 时立即返回，后台 `VideoCreationJobManager` 统一保存：

```text
job_id
status
source/model/avatar/title
generated_duration_ms
first_media_at
finalized_at
final_export_id
error_code
updated_at
```

状态机：

```text
queued → generating → completed
                 ├→ stopping → stopped
                 └→ failed
```

实现要求：

1. 至少保存于 `app.state.video_creation_jobs`，并保存后台 `asyncio.Task`。
2. API 进程退出时取消 task，不能把未完成任务伪装成成功。
3. job 状态响应不包含 RTMPS password、WHIP token、完整 endpoint query 或上游 secret-bearing error body。
4. 清理已完成任务的内存对象，但保留最终 export 和短期状态快照。
5. split worker 模式必须把 job 控制请求转发到拥有生成任务的 worker；不能只转发没有 secret 的公开快照。

为兼容现有同步客户端，默认仍为同步行为；分片发布使用 `execution_mode=async`：

```text
execution_mode 未填写或 sync → 保持旧响应语义
execution_mode=async          → 立即返回 202 和 queued job
```

新增：

```http
GET  /video-creation/jobs/{job_id}
POST /video-creation/jobs/{job_id}/stop
DELETE /video-creation/jobs/{job_id}
```

### 阶段 E：视频创作 RTMPS job API（已实现）

路由实现位于 `apps/api/routes/rtmps_jobs.py`，鉴权复用 streaming control token。

#### E.1 创建

```http
POST /streaming/rtmps-jobs
Authorization: Bearer <OPENTALKING_STREAMING_CONTROL_TOKEN>
Content-Type: application/json
```

请求结构：

```json
{
  "source": {
    "type": "video_creation_job",
    "job_id": "<video_creation_job_id>"
  },
  "transport": {
    "endpoint": "rtmps://127.0.0.1:1936/live",
    "stream_key": "rtmps-test",
    "username": "publisher",
    "password": "<OPENTALKING_HARNESS_RTMPS_PASSWORD>"
  },
  "playback": {
    "mode": "once",
    "pace": "realtime",
    "chunk_duration_ms": 500
  },
  "profile": {
    "fps": 25,
    "video_bitrate_kbps": 2500,
    "gop_seconds": 1
  },
  "auto_connect": true
}
```

密码只在创建请求内使用；不能写入数据库、Redis、前端 localStorage、日志或状态返回体。返回示例：

```json
{
  "rtmps_job_id": "rtjob_abc123",
  "video_creation_job_id": "job_123",
  "status": "waiting_source",
  "transport": "rtmps",
  "secret_configured": true,
  "generated_duration_ms": 0,
  "published_duration_ms": 0,
  "buffer_duration_ms": 0,
  "sent_video": 0,
  "sent_audio": 0,
  "bytes_sent": 0,
  "dropped_chunks": 0
}
```

#### E.2 查询、停止、重连、删除

```http
GET    /streaming/rtmps-jobs/{rtmps_job_id}
POST   /streaming/rtmps-jobs/{rtmps_job_id}/stop
POST   /streaming/rtmps-jobs/{rtmps_job_id}/reconnect
DELETE /streaming/rtmps-jobs/{rtmps_job_id}
```

状态至少包括：

```text
waiting_source | generating | connecting | publishing |
reconnecting | finalizing | completed | stopped | failed
```

错误字段只允许安全的分类值，例如：

```text
source_not_found
source_failed
tls_error
auth_error
broken_pipe
backpressure_timeout
encoder_error
upstream_closed
video_export_failed
```

不要把 `BrokenPipeError` 的完整 PyAV/FFmpeg 文本直接回传给浏览器；日志也要先去除潜在 URL query。

#### E.3 RTMPS target ownership

同一个 `endpoint + application path + stream_key` 在同一进程内只能有一个活动 publisher。目标标识只在内存中使用，不包含 RTMPS password；第二个 job 创建时返回 HTTP `409` 和 `target_replaced`，不能让两个 publisher 互相触发无限重连。

以下路径都必须释放 target ownership：

- publisher 正常完成、失败或用户停止；
- `publisher.start()` 失败；
- 重连创建新订阅或新 publisher 失败；
- watcher 退订旧 `ChunkQueue`。

当前 `ChunkedRTMPSJobManager` 是单进程内存 manager，适用于现有单 worker/unified 启动方式。若部署多个 API worker 或多个实例，必须把 target ownership 改为带 TTL 的 Redis lease，并把带 password 的恢复动作保留在用户重新提交凭据的请求内；不能依靠无 secret 的快照自动重连。

### 阶段 F：Studio 前端（已实现）

修改：

```text
apps/web/src/lib/api.ts
apps/web/src/components/VideoCreationWorkspace.tsx
```

前端操作顺序必须是：

1. 在“视频创作”中选择模型、数字人、音频/TTS、标题和画面配置。
2. 勾选“边生成边发布 RTMPS”。
3. 填写 RTMPS 发布 endpoint、stream key、username、password。
4. 点击“生成并保存”。勾选分片发布后，该按钮会同时启动视频生成和 RTMPS 发布。
5. 前端先创建异步 `VideoCreationJob`，拿到 `video_creation_job_id`。
6. 再创建 `RTMPSJob`，传入这个 job id；不能等待 `export_video` 返回后才创建。
7. 轮询或订阅两个状态：生成状态和发布状态。
8. 页面显示生成时长、发布时长、buffer、RTMPS 状态、sent video/audio、bytes 和 dropped chunks。
9. 生成完成后显示 `final_export_id` 和 MP4 下载链接。
10. 用户点击停止时同时停止生成任务和 RTMPS job；这是主动停止，不发送正常 EOF，不自动重连，并按产品策略保留或标记未完成的 MP4。

前端禁止：

- 把发布密码写入 URL、localStorage 或错误 toast。
- 把 `OPENTALKING_HARNESS_WHIP_TOKEN` 填入 RTMPS password。
- 把 WHEP 的 `reader:<读取密码>` 填入 RTMPS password。
- 以 `export_video` 出现作为“开始推流”的触发条件。

## 6. 代码验收清单

### 6.1 单元测试

```bash
cd "$OPENTALKING_HOME"

.venv/bin/pytest \
  tests/unit/test_media_chunks.py \
  tests/unit/test_rtmps_chunked_publisher.py \
  tests/unit/test_rtmps_destination.py \
  tests/unit/test_whip_publisher.py \
  tests/unit/test_whip_sdp.py \
  tests/unit/test_media_assertions.py \
  -q
```

至少覆盖：

- 第一片含关键帧和配置帧。
- chunk 边界不重置 PTS。
- 500 ms、1000 ms、2000 ms 三种分片时长。
- queue 满时背压而不是 drop。
- BrokenPipeError 后从关键帧重连。
- 正常 EOF 进入 `completed`，异常 EOF 进入 `failed`。
- RTMPS secret 不出现在日志和 public status。

### 6.2 API 和异步任务测试

```bash
.venv/bin/pytest \
  apps/api/tests/test_video_creation.py \
  apps/api/tests/test_video_creation_async.py \
  apps/api/tests/test_session_outputs.py \
  -q
```

验证：

- `execution_mode=async` 在首个视频 chunk 产生前返回 `202`。
- `GET /video-creation/jobs/{id}` 可以观察到 `generating`。
- RTMPS job 可以在 source 仍为 `generating` 时创建并进入 `waiting_source`/`publishing`。
- `final_export_id` 只在 MP4 归档完成后出现。
- 服务重启后不恢复带 secret 的 publisher；旧快照只能显示 failed/stale。

### 6.3 前端静态检查

```bash
cd "$OPENTALKING_HOME/apps/web"
npm run typecheck
npm run build
```

## 7. 本地端到端执行步骤

下面步骤适用于服务器重启后的重新启动，也适用于第一次联调。不要通过“先进入实时对话、说一句话、再进入流媒体”来测试本链路；视频创作分片 RTMPS 不依赖实时 Session。

### 7.1 启动服务和 harness

```bash
cd "$OPENTALKING_HOME"
set -a
. outputs/streaming/credentials.env
set +a

export OPENTALKING_API_HOST=0.0.0.0
export OPENTALKING_API_PORT=8210
export OPENTALKING_UNIFIED_HOST=0.0.0.0
export OPENTALKING_UNIFIED_PORT=8210
export OPENTALKING_WEB_HOST=0.0.0.0
export OPENTALKING_WEB_PORT=5280
export OPENTALKING_DEFAULT_MODEL=mock
export OPENTALKING_STREAMING_ENABLED=1
export OPENTALKING_STREAMING_ALLOW_LOCAL_TARGETS=1
export OPENTALKING_STREAMING_TEST_AUTH_BYPASS=1
export OPENTALKING_STREAMING_RTMPS_CA_FILE="$PWD/outputs/streaming/tls/ca.crt"
export OPENTALKING_STREAMING_WHIP_CA_FILE="$PWD/outputs/streaming/tls/ca.crt"

docker compose -f docker/docker-compose.streaming-test.yml up -d
bash scripts/start_unified.sh --mock --api-port 8210 --web-port 5280

curl -fsS http://127.0.0.1:8210/health >/dev/null
curl -fsS http://127.0.0.1:5280 >/dev/null
docker inspect docker-mediamtx-1 --format 'network={{.HostConfig.NetworkMode}}'
```

如果 API 或 WebUI 已经在运行，不要重复启动；先执行：

```bash
curl -fsS http://127.0.0.1:8210/health >/dev/null && echo API_OK
curl -fsS http://127.0.0.1:5280 >/dev/null && echo WEB_OK
ss -ltnup | rg ':(8210|5280|1936|8554|8888|8889)\\b'
```

同一台服务器上的浏览器打开 `http://127.0.0.1:5280`；远程浏览器打开 `http://<服务器公网IP>:5280`。若只开放了 8210 而没有开放 5280，API 正常但页面仍会“端口打不开”。远程 HLS 还必须放行 `8888/tcp`；远程 WHEP 另需放行 `8889/tcp`、`8189/udp` 和 `8190/tcp`。

`network=host`、`1936/tcp`、`8554/tcp`、`8888/tcp`、`8889/tcp`、`8189/udp`、`8190/tcp` 都必须正常。视频创作的 RTMPS publisher 运行在 API 主机上，因此它可以使用 `127.0.0.1`；浏览器访问 HLS/WHEP 时才需要使用页面主机名或服务器公网 IP。

### 7.2 创建异步视频任务

下面以 `mock` 轻量模式和 TTS 文本为例。推荐使用 `dogo-light2d` 数字人，生成速度和依赖最适合本地链路验收。`execution_mode=async` 已经支持。

```bash
BASE=http://127.0.0.1:8210

curl --fail-with-body -sS -X POST "$BASE/video-creation/jobs" \
  -F 'execution_mode=async' \
  -F 'model=mock' \
  -F 'avatar_id=dogo-light2d' \
  -F 'audio_source=tts_text' \
  -F 'text=这是视频生成过程中分片发布 RTMPS 的验收片段。' \
  -F 'tts_provider=mock' \
  -F 'title=chunked-rtmps-smoke' \
  -o /tmp/video-job.json

cat /tmp/video-job.json
VIDEO_JOB_ID=$(python -c 'import json; print(json.load(open("/tmp/video-job.json"))["job_id"])')
```

轮询直到进入 `generating`，不要等待 `completed`：

```bash
for i in $(seq 1 60); do
  curl -fsS "$BASE/video-creation/jobs/$VIDEO_JOB_ID" | tee /tmp/video-job-status.json
  python - <<'PY'
import json
p=json.load(open('/tmp/video-job-status.json'))
print('status=', p.get('status'), 'generated_ms=', p.get('generated_duration_ms'), 'export=', p.get('final_export_id'))
PY
  status=$(python -c 'import json; print(json.load(open("/tmp/video-job-status.json")).get("status", ""))')
  case "$status" in generating|finalizing|completed) break;; failed|stopped) exit 1;; esac
  sleep 1
done
```

### 7.3 立即创建 RTMPS job

创建请求必须在视频任务仍处于 `generating` 时发送，用来证明 RTMPS 没有等待最终 MP4。下面的 Python 请求在进程内读取密码，避免把密码放进 shell 命令参数或日志：

```bash
VIDEO_JOB_ID="$VIDEO_JOB_ID" .venv/bin/python - <<'PY' > /tmp/rtmps-job.json
import json, os
import httpx

base = os.environ.get("BASE", "http://127.0.0.1:8210")
job_id = os.environ["VIDEO_JOB_ID"]
headers = {}
if os.environ.get("OPENTALKING_STREAMING_CONTROL_TOKEN"):
    headers["Authorization"] = "Bearer " + os.environ["OPENTALKING_STREAMING_CONTROL_TOKEN"]
payload = {
    "source": {"type": "video_creation_job", "job_id": job_id},
    "transport": {
        "endpoint": "rtmps://127.0.0.1:1936/live",
        "stream_key": "rtmps-test",
        "username": os.environ["OPENTALKING_HARNESS_RTMPS_USERNAME"],
        "password": os.environ["OPENTALKING_HARNESS_RTMPS_PASSWORD"],
    },
    "playback": {"mode": "once", "pace": "realtime", "chunk_duration_ms": 500},
    "profile": {"fps": 25, "video_bitrate_kbps": 2500, "gop_seconds": 1},
    "auto_connect": True,
}
with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
    response = client.post("/streaming/rtmps-jobs", headers=headers, json=payload)
    response.raise_for_status()
    print(json.dumps(response.json()))
PY

cat /tmp/rtmps-job.json
RTMPS_JOB_ID=$(python -c 'import json; print(json.load(open("/tmp/rtmps-job.json"))["rtmps_job_id"])')
```

如果创建后视频任务已经是 `completed`，这次测试不能作为“边生成边发布”证据，应重新使用更长的测试文本或更慢的模型，并在第一段生成后立刻创建 RTMPS job。

### 7.4 采集 RTMPS 转入的完整音视频

RTMPS 发布成功后，从 MediaMTX 的 RTSP 播放路径采集。脚本默认从当前 shell 的 `OPENTALKING_HARNESS_READ_USERNAME/PASSWORD` 读取接收凭据，不要把密码写进 URL：

```bash
rm -rf /tmp/chunked-rtmps-capture
mkdir -p /tmp/chunked-rtmps-capture

.venv/bin/python scripts/streaming/receive_rtmps.py \
  --url rtsp://127.0.0.1:8554/live/rtmps-test \
  --output /tmp/chunked-rtmps-capture/capture.mp4 \
  --seconds 30

ffprobe -v error -show_entries \
  stream=codec_type,codec_name,width,height,sample_rate,duration \
  -of json /tmp/chunked-rtmps-capture/capture.mp4
```

应看到 `h264` 和 `aac`，并且音频采样率通常为 `48000`。RTSP capture 的开始时间必须早于视频任务的 `finalized_at`。

`receive_rtmps.py` 会对视频和音频分别重建单调输出 PTS，适用于接收端在 RTMPS 流已经开始后才加入的情况；不要用跨音视频的网络到达顺序直接判断 PTS 是否单调。

### 7.5 检查时间戳、间隔和 A/V 漂移

```bash
ffprobe -v error -show_streams -show_packets -show_frames -of json \
  /tmp/chunked-rtmps-capture/capture.mp4 \
  > /tmp/chunked-rtmps-capture/ffprobe.json

.venv/bin/python scripts/streaming/assert_media_timeline.py \
  --ffprobe-json /tmp/chunked-rtmps-capture/ffprobe.json \
  --video-max-gap-ms 120 \
  --audio-max-gap-ms 60 \
  --av-drift-p95-ms 100 \
  --av-drift-max-ms 250
```

### 7.6 检查 job 状态和最终 MP4

```bash
curl -fsS "$BASE/streaming/rtmps-jobs/$RTMPS_JOB_ID" \
  | tee /tmp/rtmps-job-final.json
curl -fsS "$BASE/video-creation/jobs/$VIDEO_JOB_ID" \
  | tee /tmp/video-job-final.json

python - <<'PY'
import json
rt=json.load(open('/tmp/rtmps-job-final.json'))
vc=json.load(open('/tmp/video-job-final.json'))
assert rt.get('status') == 'completed', rt
assert vc.get('status') == 'completed', vc
assert int(rt.get('sent_video', 0)) > 0, rt
assert int(rt.get('sent_audio', 0)) > 0, rt
assert int(rt.get('dropped_chunks', 0)) == 0, rt
assert vc.get('final_export_id'), vc
print('chunked RTMPS job OK')
PY
```

### 7.7 Studio 前端操作（推荐的人工验收路径）

1. 打开 WebUI：本机用 `http://127.0.0.1:5280`，远程用 `http://<服务器公网IP>:5280`。不要访问 `5180`。
2. 点击左侧“视频创作”，进入“离线数字人口播”；不要先进入“实时对话”，也不要用“流媒体”页里的 `Studio RTMPS` 作为本项验收对象。
3. 选择数字人。纯本地无 GPU 验收可选 `dogo-light2d`，模型会显示为“轻量模式”（后端值为 `mock`）。音频源选择“口播合成”，TTS provider 选择 `mock`（若页面已固定为 mock 也可以保持默认）。文本建议使用能生成约 10 秒以上视频的内容。
4. 勾选“边生成边发布 RTMPS”。填写以下字段：

   | 前端字段 | 应填写的值 |
   | --- | --- |
   | RTMPS endpoint | `rtmps://127.0.0.1:1936/live` |
   | Stream key | `rtmps-test` |
   | 发布用户名 | `publisher` |
   | 发布密码 | 当前 shell 中 `$OPENTALKING_HARNESS_RTMPS_PASSWORD` 的值 |
   | Streaming control token | 本地 test bypass 留空；非 bypass 服务填写 `$OPENTALKING_STREAMING_CONTROL_TOKEN` 的值 |

   这里的 endpoint 是“后端 publisher 连接 MediaMTX”的地址，所以即使浏览器从远程访问，后端和 MediaMTX 在同一台服务器时仍填写 `127.0.0.1`。不要填 `OPENTALKING_HARNESS_WHIP_TOKEN`，也不要填 `reader:<读取密码>`。
5. 点击“生成并保存”。前端会先创建异步视频任务，再立刻创建视频创作 RTMPS job；不会等最终 MP4 生成完才推流。
6. 页面应依次看到：生成状态 `queued/generating`，RTMPS 状态 `connecting/publishing`，随后 RTMPS `completed`。发布过程中应看到 `健康/状态`、生成/发布时长、缓冲、媒体帧和发送字节；`丢弃分片` 应为 `0`。
7. 生成结束后页面出现 MP4 预览和下载按钮。MP4 是并行归档结果；它出现之前 RTMPS 已经应该有 `sent_video`、`sent_audio` 和接收端媒体。
8. 要在前端直接观看 RTMPS 的完整音视频，在页面出现 `RTMPS: publishing` 后，HLS 播放地址保持默认的 `/streaming/hls/live/rtmps-test/index.m3u8`，填写 `reader:<读取密码>`，点击“开始浏览器预览”。视频创作 once 播放器会从当前 HLS 窗口的最早可用位置启动，并使用标准 fMP4 HLS；目标首帧等待约 1～3 秒。如果浏览器阻止带声音自动播放，点击视频控件左下角的播放按钮。
9. 需要文件级验收时，再在另一个终端使用第 7.4 节的 RTSP receiver；HLS 和 RTSP 都应保留 H.264/AAC。

HLS 是直播播放链路。MediaMTX 使用标准 fMP4 HLS、1 秒 segment 和 30 个保留 segment；视频创作还使用 500ms 生产分片和 1 秒 GOP，以缩短首帧等待并保留开头。若口播视频短于播放器启动窗口，RTMPS 可能已经正常完成而 HLS 还没来得及上线；此时页面会显示“发布完成，预览结束”，应直接播放同页下方的最终 MP4（该 MP4 仍包含画面和 AAC 声音）。这不是 Token 错误。

如果页面显示 `Studio RTMPS / healthy / BrokenPipeError`，说明你正在看实时 Session output，而不是本节的 VideoCreation RTMPS job。回到“视频创作”并检查该页面下方的“RTMPS”状态、`rtmps_job_id` 对应的发布统计和 RTSP capture。

### 7.8 在「流媒体」页接收 RTMPS（推荐 HLS）

1. 不要点击“打开接收服务”，也不要填写 WHEP endpoint。
2. 打开「流媒体」页，在“接收端 · HLS 浏览器播放器（RTMPS 推荐）”中确认：

   ```text
   HLS 播放地址：/streaming/hls/live/rtmps-test/index.m3u8
   浏览器接收 Token：reader:<读取密码>
   ```

3. 点击“开始 HLS 接收”，视频控件出现后点击播放按钮。HLS 状态应显示“播放中”，浏览器 `muted` 应为 `false`，画面和 AAC 声音同时输出。
4. 「浏览器 WHEP 播放器（WHIP 专用）」只用于 WHIP 的 H.264/Opus；不要用它验收 RTMPS AAC。

## 8. 失败定位表

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `RTMPS connected` 但没有 `generated_duration_ms` | 测试的是 Session output，不是视频创作 RTMPS job | 检查是否创建了 `/streaming/rtmps-jobs`，并核对 `video_creation_job_id` |
| `BrokenPipeError` | 上游关闭 socket、连接重置或 publisher flush 时写入失败 | 看 `reconnecting`、重连次数、最近关键帧和 `last_error=broken_pipe`；不能继续显示 healthy |
| RTMPS 首帧在 MP4 完成后才到 | 仍把完整 MP4 当 RTMPS 输入，或 publisher 在等待 export | 检查 `ChunkQueue.put()` 是否在每批 render 后调用 |
| `connected`、bytes 增长但接收黑屏 | 第一片没有 IDR/SPS/PPS，或晚加入没有周期性关键帧 | 检查 encoder GOP、第一片 `starts_with_keyframe` 和重连 replay |
| RTSP 有视频无音频 | AAC stream 未建立、音频 PTS 不连续或尾部没有 flush | 检查 audio frame、sample rate、AAC config 和 muxer flush |
| HLS 播放器 401/500 或一直加载 | 首次认证失败、流还没 online、旧 HLS session 已结束，或 API/HLS 代理未重启 | 首次 401/403 才检查 `reader:<读取密码>`；已经播放过媒体后遇到 401/403 属于 session 更新，播放器会在发布期间自动重连；两个 job 都完成后显示“预览结束”，不再误报 Token。HLS 地址使用 `/streaming/hls/live/rtmps-test/index.m3u8`，必要时重启 API/WebUI |
| WHEP `failed` | 证书未接受、Bearer 用错、ICE 端口不可达 | 先访问 `8889` 接收服务接受证书，token 使用 `reader:<读取密码>`，检查 `8189/8190` |
| RTMPS 的 WHEP 有视频无声音 | MediaMTX 1.20 的 AAC→Opus 能力边界 | 改用 HLS 浏览器播放器或 `rtsp://.../live/rtmps-test`，不要改成 WHIP token |
| `dropped_chunks > 0` | 使用了实时 publisher 的丢帧队列或队列太小 | 视频创作必须使用阻塞队列；调整 buffer 或触发 backpressure |
| PTS 非单调 | 每个 chunk 重新从 0 编号、跨编码器错误复用 time base | 统一 job media clock，按视频/音频各自 time base 递增 |
| 任务重启后显示 healthy | 恢复了没有 secret 的旧 publisher snapshot | publisher secret 只能在内存，重启后旧 output 应为 stale/failed，需要重新创建 |

## 9. 完成定义（Definition of Done）

当前实现的完成标准：

- `VideoCreationService` 在第一批 frames 生成后即可向 `ChunkSink` 发送。
- RTMPS publisher 使用单一持续连接，正常 EOF 可完成，断线可从关键帧重连。
- 生成速度快时队列背压，`dropped_chunks=0`。
- RTMPS capture 为 H.264 + AAC，PTS 单调，视频/音频间隔和 A/V drift 达标。
- 记录并证明 `t_first_rtmps < t_final_mp4`。
- 最终 MP4 仍能创建并可下载，`final_export_id` 只在归档完成后填充。
- WHIP 实时数字人链路没有被新 publisher 改坏。
- Studio 前端能够填写 RTMPS 发布参数、显示两个独立进度、停止任务和展示最终 MP4。
- 密码/token 不出现在日志、Redis、状态接口、localStorage、URL 或异常 toast。
- targeted pytest、API 测试、前端 typecheck/build、MediaMTX compose config 全部通过。

## 10. 清理测试资源

```bash
# 停止并删除本地 MediaMTX harness 容器；不会删除代码。
docker compose -f docker/docker-compose.streaming-test.yml down -v

# 删除本次临时 capture 和状态文件。
rm -rf /tmp/chunked-rtmps-capture /tmp/video-job.json /tmp/video-job-status.json /tmp/rtmps-job.json
```

不要提交以下内容：

```text
outputs/streaming/credentials.env
outputs/streaming/tls/*.key
outputs/streaming/tls/*.crt
capture.mp4 / ffprobe.json / 临时 job 状态
examples/avatars/custom-* 用户资产
```
