# OpenTalking RTMPS + WHIP 开发交接

更新时间：2026-08-13 00:00（Asia/Shanghai）

## 继续工作的入口

- 仓库：`/home/lyf/opentalking`
- 分支：`feat/standalone-rtmps-whip`
- 远端：`origin/feat/standalone-rtmps-whip`
- 最近提交：
  - `1dfd739 test: cover split worker auth and action idempotency`
  - `a0362b7 feat: harden streaming state and receiver safety`
  - `8b0f9cb feat: add RTMPS and WHIP streaming outputs`
- Enterprise 仓库不在本次范围内，不要修改 `/home/lyf/opentalking-enterprise`。

完整执行基线仍是：
`docs/zh/roadmap/opentalking-standalone-rtmps-whip-implementation-plan-2026-08-12.md`

## 已完成

- ProgramClock、ProgramOutputManager、独立 branch/queue；SessionRunner 和 FlashTalkRunner 均已接入，关闭 flag 时保留旧 WebRTC sink。
- Session output API：RTMPS/WHIP 创建、查询、连接、断开、重连、删除；typed transport schema、控制 token、split worker 内部 token、SSRF/目标校验。
- RTMPS：PyAV H.264/AAC/FLV、TLS 预校验、批准 IP pinning、有限重连、媒体健康和 PTS 指标。
- WHIP：aiortc H.264/Opus offerer、full ICE、SDP 校验、受控 redirect、带 Bearer 的 resource DELETE、失败清理、pinned HTTP transport、candidate policy。
- Redis/InMemoryRedis secret-free snapshot/index、TTL、worker boot/owner epoch、stale worker fail-closed；create/action/speak 幂等收据。
- Studio“流媒体”页面：RTMPS/WHIP 发送、输出状态管理、浏览器 WHEP 接收播放器和 RTMPS 接收地址。
- 固定 MediaMTX 1.20.0 harness、临时 PKI/凭据、RTMPS PyAV 接收器、WHEP 接收器和媒体断言脚本。

## 已验证

- 相关 backend/API/streaming 测试：30 passed（最近一次 targeted run）。
- streaming 目标文件 Ruff、mypy 通过。
- Studio：`npm run typecheck`、`npm run test`（15 passed）、`npm run build` 通过。
- 根 compose 和 streaming-test compose 配置解析通过。
- 本机真实 MediaMTX 链路通过：RTMPS H.264/AAC timeline、WHIP/WHEP H.264/Opus SDP/stats。
- 当前测试运行服务：API `http://127.0.0.1:8210`、Studio `http://127.0.0.1:5280`、MediaMTX RTMPS `1936`、WHIP/WHEP `8889`、RTSP `8554`。
- Docker API 构建已进入正确的 flat-layout COPY，但 Debian `apt-get update` 因当前网络源长时间无响应；不要把它描述为构建通过。

## 下一步优先级

1. 在可用 Docker/网络环境重跑 API、worker、flashtalk 镜像构建。
2. 补独立故障注入：只断 RTMPS ingest、只删/断 WHIP resource，确认另一 branch 持续收流并自动 fresh reconnect。
3. 做浏览器 WHEP 实际播放检查；运行 synthetic idle/speech/interrupt soak。
4. 运行 2 小时 idle/speech soak 和 release 8 小时 RTMPS soak；记录 PTS gap、A/V drift、内存和任务泄漏。
5. 完成第二个固定版本 WHIP endpoint（若没有可复现环境，不要宣称已完成）。
6. 最终审查 Definition of Done，未实际运行的门禁保持未勾选。

## 重要约束

- 不创建 PR；只 push 当前分支。
- 不提交 `.env`、`outputs/streaming/`、capture、证书/私钥、凭据或模型权重。
- `examples/avatars/custom-*` 是用户本地未跟踪资产，必须保留但不能 `git add`。
- streaming 默认关闭；生产不能开启 local-target/test bypass；不要把 secret 写 Redis、日志、SSE、错误响应或命令行参数。
- `OPENTALKING_STREAMING_INTERNAL_CONTROL_TOKEN` 不能回退使用公开 control token。

## 当前 Codex 会话问题

用户遇到的 `invalid_encrypted_content` 来自旧 Codex 代理会话的加密 reasoning 状态，不是 OpenTalking API。旧线程历史过大且跨模型切换后无法验证旧 encrypted item；OpenTalking 使用 DashScope OpenAI-compatible Chat Completions，日志中没有该字段。继续工作时请新建 Codex 会话，不要 resume 损坏的旧线程；从本文件和当前分支状态恢复即可。
