# 开发说明

## 目录速览

```text
apps/
  api/        FastAPI 路由与服务
  unified/    单进程入口
  web/        React + Vite 前端
src/opentalking/
  avatars/    头像清单、加载与校验
  core/       配置、存储、接口、类型
  events/     事件模型
  llm/        OpenAI 兼容流式客户端
  models/     wav2lip / musetalk / flashtalk 适配
  rtc/        aiortc 封装
  server/     FlashTalk WebSocket 服务
  tts/        Edge / ElevenLabs / XTTS / CosyVoice
  worker/     SessionRunner、FlashTalkRunner、任务消费
```

## 本地开发推荐流程

### 后端

```bash
pip install -e ".[dev,models]"
bash scripts/start_unified.sh
```

### 前端

```bash
cd apps/web
npm ci
VITE_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev
```

## 常用检查命令

```bash
ruff check src apps tests
pytest tests apps/api/tests apps/worker/tests -v
cd apps/web && npm run typecheck
```

仓库里的 `Makefile` 也提供了基础命令:

```bash
make lint
make test
make build-web
```

## 调试技巧

### 导出一次播报的调试产物

```bash
export OPENTALKING_DEBUG_DUMP_SPEECH_DIR=./debug
```

播报结束后会输出:

- `tts.wav`
- `rendered_silent.mp4`
- `rendered_with_audio.mp4`
- `meta.json`

### 切换 Wav2Lip live 模式

```bash
export OPENTALKING_WAV2LIP_LIVE_MODE=streaming
```

可选值见当前实现:

- `streaming`
- `official`
- `auto`

### 前端默认代理

`apps/web/vite.config.ts` 的默认代理目标是:

```text
http://127.0.0.1:8010
```

前端开发端口固定为 `5175`。

## 当前已知约束

- `prepare-avatar.sh` 还是占位脚本，头像预处理主要靠现有样例或自定义脚本
- 自带 React 前端默认依赖 `/tts/voices`，所以优先配合统一模式调试
