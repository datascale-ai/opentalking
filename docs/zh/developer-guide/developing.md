# 开发流程

本页说明 OpenTalking 自身的开发流程：仓库结构、环境搭建、本地运行、Lint、测试与调试。

## 仓库结构

```text
opentalking/
├── opentalking/          # 库代码（flat layout）
│   ├── core/             # 接口、注册表、类型、配置、总线
│   ├── models/           # 本地合成适配器（quicktalk）与远端 shim
│   ├── llm/  tts/  stt/  # Provider 适配器
│   ├── rtc/              # WebRTC track 管理
│   ├── voices/           # 声音复刻（CosyVoice、Qwen、ElevenLabs）
│   ├── avatars/          # Avatar bundle 加载与校验
│   ├── worker/           # 流水线编排
│   └── server/  cli/  engine/
├── apps/
│   ├── api/              # FastAPI 路由与 schema
│   ├── worker/           # Worker 入口
│   ├── unified/          # 单进程入口
│   ├── cli/              # 命令行工具
│   └── web/              # React 前端（TypeScript、Vite）
├── configs/              # default.yaml、profiles/*、synthesis/*
├── scripts/quickstart/   # 启停辅助脚本
├── examples/avatars/     # 示例 Avatar bundle
├── tests/                # pytest 套件
└── docs/                 # 文档站
```

## 环境搭建

```bash title="终端"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

`[dev]` extra 安装 `ruff`、`pytest`、`pytest-asyncio`、`pytest-cov` 等开发依赖。

## 本地运行

OpenTalking 可在四种配置下本地运行，分别对应不同的开发范围。

### Unified 模式 + mock 合成

推荐配置，适用于前端、编排、API/schema 修改场景。**不依赖 GPU**。

```bash title="终端"
bash scripts/quickstart/start_all.sh --mock
```

- 后端：<http://127.0.0.1:8000>
- 前端：<http://localhost:5173>

Python 源码修改自动 reload：

```bash title="终端"
uvicorn apps.unified.main:app --reload --port 8000
```

前端在独立终端中运行：

```bash title="终端"
cd apps/web && npm ci && npm run dev -- --host 0.0.0.0
```

Vite 默认启用 HMR；后端修改须重启，或使用 `uvicorn --reload`。

### Unified 模式 + 真实 backend

引入真实 talking-head 模型。默认 Wav2Lip 路径使用 OmniRT；本地 adapter 与单模型
WebSocket 服务可通过 `models.<name>.backend` 或 `OPENTALKING_<MODEL>_BACKEND` 选择。

```bash title="终端：启动 OmniRT（终端 1）"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

```bash title="终端：opentalking（终端 2）"
echo "OMNIRT_ENDPOINT=http://127.0.0.1:9000" >> .env
bash scripts/quickstart/start_all.sh
```

OmniRT 可达后，前端模型选择器列出 `wav2lip`。
各模型权重下载与启动命令见 [模型](../model-deployment/index.md)。

### API 与 Worker 分离 + 本地 Redis

调试事件总线或 Worker 生命周期时使用。

```bash title="终端：redis"
redis-server --port 6379 --save "" --appendonly no
```

```bash title="终端：API"
export OPENTALKING_REDIS_URL=redis://localhost:6379/0
export OPENTALKING_WORKER_URL=http://127.0.0.1:9001
uvicorn apps.api.main:app --reload --port 8000
```

```bash title="终端：Worker"
export OPENTALKING_REDIS_URL=redis://localhost:6379/0
python -m apps.worker.main --port 9001
```

```bash title="终端：前端"
cd apps/web && npm run dev -- --host 0.0.0.0
```

共四个进程并发运行。使用 `redis-cli MONITOR` 观察总线流量。

### 仅前端

后端已在其他主机运行时：

```bash title="终端"
cd apps/web
export VITE_BACKEND_URL=http://teammate-host:8000
npm run dev -- --host 0.0.0.0
```

停止 quickstart 辅助脚本启动的全部进程：

```bash title="终端"
bash scripts/quickstart/stop_all.sh
```

手工启动的组件须自行终止对应的 `uvicorn`、`python -m apps.worker.main` 或
`redis-server` 进程。

## Lint 与格式化

```bash title="终端"
ruff check opentalking apps tests
ruff format opentalking apps tests
```

pre-commit 钩子在 git commit 时自动对暂存文件执行上述检查。

## 测试

```bash title="终端"
pytest tests -v
# 单一测试文件：
pytest tests/test_session_state.py -v
# 覆盖率报告：
pytest tests --cov=opentalking --cov-report=term-missing
```

测试约定：

- 异步测试使用 `pytest_asyncio`，共享 fixture 定义于 `conftest.py`。
- HTTP 外部调用通过 `respx` mock；WebSocket 调用通过 `pytest-aiohttp` mock。
- 调用真实语言模型或语音合成服务的测试由 `OPENTALKING_TEST_LIVE=1` 门控，默认关闭。

## 调试

### 详细日志

```bash title="终端"
OPENTALKING_LOG_LEVEL=DEBUG opentalking-unified
```

### Server-sent event 流

`POST /sessions` 创建会话后：

```bash title="终端"
curl -N http://127.0.0.1:8000/sessions/<id>/events
```

流中交错出现 `transcript`、`llm`、`tts`、`status` 事件以及帧时序标记。

### Redis 总线检视

```bash title="终端"
redis-cli MONITOR
```

### 直接调用端点

```bash title="终端"
# 列出 avatar
curl -s http://127.0.0.1:8000/avatars | jq

# 创建会话
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'

# 合成固定文本
curl -s -X POST http://127.0.0.1:8000/sessions/<id>/speak \
  -H 'content-type: application/json' \
  -d '{"text":"你好世界"}'
```

完整端点列表详见 [API 参考](../api-reference/index.md)。

## 常见问题

| 现象 | 可能原因 |
|------|---------|
| `ModuleNotFoundError: opentalking` | 未执行 `pip install -e ".[dev]"`。 |
| 浏览器提示 WebRTC 不可用 | 浏览器在非 HTTPS、非 localhost origin 上拒绝 WebRTC。 |
| Worker 日志输出 `redis connection refused` | 切换至 unified 模式，或先启动 `redis-server`。 |
| 测试在 `await ws.send_text()` 卡住 | `OPENTALKING_TEST_LIVE` 已开启但真实服务不可达。 |

## Pull request 清单

提交 PR 前确认：

- [ ] `ruff check` 通过（pre-commit 钩子强制）。
- [ ] `pytest tests` 通过。
- [ ] 用户可见的行为变更同步至 `README.md` 或相关文档页。
- [ ] 新增代码路径附带测试。
- [ ] Commit 按改动范围切分（adapter、route、worker 等），便于审阅。

更多规范见 [贡献指南](contributing.md)。
