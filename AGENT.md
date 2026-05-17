# AGENT.md

本文件给进入 OpenTalking 仓库的团队 agent 使用。开始任何任务前先读本文件，再按任务类型读取对应 README、docs、配置和测试。这里记录的是当前代码形态下的协作规则，不替代源码。

## 任务入口

先确认工作目录和状态：

```bash
cd <opentalking-repo>
git status --short
```

优先使用 `rg` / `rg --files` 查找文件和符号。不要用旧记忆里的 `src/opentalking/...` 路径；当前 OpenTalking 是 flat layout，库代码在仓库根目录的 `opentalking/`，应用入口在 `apps/`。

做代码修改前先读：

- `README.md`：当前用户路线、启动入口、模型部署叙事。
- `docs/zh/docs/architecture.md`：系统架构、组件职责、OpenTalking 与 backend 边界。
- `docs/zh/docs/model-adapter.md`：`mock` / `local` / `direct_ws` / `omnirt` backend 规则。
- `docs/zh/model-deployment/talking-head.md`：模型路线和状态说明。
- `configs/default.yaml`：当前默认配置。
- `pyproject.toml`、`Makefile`、`apps/web/package.json`：开发、测试、构建命令。

英文文档存在于 `docs/en/`。用户可见的能力或命令变更通常需要同步 `docs/zh/` 和 `docs/en/`，或在 PR 说明中明确尚未同步。

## 项目边界

OpenTalking 是实时数字人对话编排层，负责：

- WebUI、API、会话状态、事件流、WebRTC。
- LLM、STT、TTS provider 的调用和串联。
- Avatar / voice 资产管理。
- `LLM -> TTS -> talking-head backend -> WebRTC` 的运行时流水线。
- 按模型选择 `mock`、`local`、`direct_ws` 或 `omnirt` backend。

OpenTalking 不负责：

- 重模型权重的完整生命周期和多卡调度。
- OmniRT 内部 worker、队列、CUDA / Ascend runtime。
- LLM、TTS、STT 服务本身的托管。
- TURN、认证、账号、生产级权限系统。

OmniRT 是可选的外部推理服务。只有模型配置为 `backend: omnirt` 时，OpenTalking 才通过 `OMNIRT_ENDPOINT` 派生 `/v1/audio2video/{model}` WebSocket 路由。Sibling repo 常见路径是：

```bash
cd <omnirt-repo>
```

OmniRT 当前是 `src/omnirt/` layout，主要入口和验证命令以 `../omnirt/README.md`、`../omnirt/pyproject.toml`、`../omnirt/docs/` 为准。

## 关键目录

```text
opentalking/
├── opentalking/
│   ├── core/          # Settings、model_config、bus、registry、types、session store
│   ├── providers/     # llm / stt / tts / rtc / synthesis provider
│   ├── models/        # 本地模型 adapter，例如 quicktalk、wav2lip
│   ├── pipeline/      # session、speak、recording 流水线
│   ├── runtime/       # worker、task consumer、timing、runtime server
│   ├── avatar/        # Avatar bundle 加载、校验、预处理
│   ├── voice/         # 音色资产和复刻存储
│   └── events/ media/ # 事件 schema、媒体工具
├── apps/
│   ├── api/           # FastAPI 路由、schema、service
│   ├── unified/       # 开发友好的单进程入口
│   ├── web/           # React + Vite + TypeScript
│   └── cli/           # doctor、download、bench 等命令
├── configs/           # default.yaml、profiles、inference、synthesis 配置
├── scripts/           # start_unified.sh、quickstart、部署辅助脚本
├── tests/             # pytest 单元和集成测试
└── docs/              # MkDocs 文档站，zh/en 双语
```

不要把 `models/` 下的权重、缓存、生成媒体、私有 avatar 资产提交进 git。

## 启动与运行

推荐入口是：

```bash
bash scripts/start_unified.sh --mock
```

常见路线：

```bash
# 首次跑通 API / WebUI / LLM / TTS / WebRTC，不需要权重
bash scripts/start_unified.sh --mock

# 消费级 GPU，本地 QuickTalk
bash scripts/start_unified.sh --backend local --model quicktalk

# 消费级 GPU，本地 Wav2Lip
bash scripts/start_unified.sh --backend local --model wav2lip

# 远端高质量模型，通过 OmniRT
bash scripts/start_unified.sh --backend omnirt --model flashtalk --omnirt http://<gpu-server>:9000
```

`scripts/quickstart/*` 仍然保留，适合更底层的服务调试、端点配置和停止服务。面向新用户或 README 流程时优先使用 `scripts/start_unified.sh`。

前端默认地址是 `http://localhost:5173`。后端端口默认 `8000`，可通过 `--api-port` 和 `--web-port` 覆盖。停止 quickstart 启动的进程：

```bash
bash scripts/quickstart/stop_all.sh
```

## 配置规则

OpenTalking 配置来源有优先级，不要只看一处就下结论：

1. 进程环境变量和 `.env`，前缀通常是 `OPENTALKING_`。
2. legacy 环境变量，例如 `OMNIRT_ENDPOINT`、`DASHSCOPE_API_KEY`、`FLASHTALK_WS_URL`。
3. `configs/default.yaml` 或 `OPENTALKING_CONFIG_FILE` / `CONFIG_FILE` 指向的 YAML。
4. 代码默认值。

模型 backend 解析位于 `opentalking/core/model_config.py`。优先级是内置默认、YAML 中 `models.<name>.backend`、再到 `OPENTALKING_<MODEL>_BACKEND` 环境变量。`scripts/start_unified.sh --backend local --model quicktalk` 会导出 `OPENTALKING_QUICKTALK_BACKEND=local` 并覆盖 YAML。

当前默认配置需要以 `configs/default.yaml` 为准。写文档或 review 时不要把 README 推荐路线和 YAML 默认值混为一谈。README 当前推荐：

| 场景 | 推荐模型 | 推荐 backend |
| --- | --- | --- |
| 首次验证 | `mock` | `mock` |
| 消费级 GPU 本地路线 | `quicktalk` | `local` |
| 轻量口型同步 | `wav2lip` | `local` / `omnirt` |
| 高质量远端推理 | `flashtalk` | `omnirt` |

backend 含义：

| backend | 含义 | 典型代码位置 |
| --- | --- | --- |
| `mock` | 内置占位合成，CI 和首次验证使用。 | `opentalking/providers/synthesis/mock.py` |
| `local` | 进程内加载 `opentalking/models/<name>/` adapter。 | `opentalking/models/` |
| `direct_ws` | 直接连接单模型 WebSocket 服务。 | `opentalking/providers/synthesis/backends.py` |
| `omnirt` | 从 `OMNIRT_ENDPOINT` 派生 OmniRT audio2video 路由。 | `opentalking/providers/synthesis/omnirt.py` |

OmniRT 相关变量写清楚：

- `OMNIRT_ENDPOINT`：OmniRT base URL，例如 `http://127.0.0.1:9000`。
- `OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE`：默认 `/v1/audio2video/{model}`。
- `OPENTALKING_OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE`：OpenTalking Settings 前缀形式。
- `OMNIRT_API_KEY`：可选 Bearer Token。
- `OPENTALKING_<MODEL>_BACKEND`：模型级 backend 覆盖，例如 `OPENTALKING_QUICKTALK_BACKEND=local`。

LLM / TTS / STT 相关变量修改时，明确区分 `.env`、`Settings`、legacy env 和请求级覆盖。TTS 前端可能传入 provider 覆盖，不要只根据 `.env` 默认值判断用户实际选择。

## 开发命令

安装 Python 依赖：

```bash
uv sync --extra dev --python 3.11
source .venv/bin/activate
```

需要本地模型 runtime 时：

```bash
uv sync --extra dev --extra models --python 3.11
```

兼容 fallback：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

前端：

```bash
cd apps/web
npm ci
npm run dev
npm run typecheck
npm run build
```

常用后端命令：

```bash
make test
make lint
pytest
pytest tests -v
pytest apps/api/tests -v
ruff check opentalking apps tests
```

`Makefile` 当前的 `make lint` 只检查部分路径：

```bash
ruff check opentalking/core opentalking/events opentalking/avatar apps tests
```

如果改动了 `opentalking/providers/`、`opentalking/pipeline/`、`opentalking/runtime/` 或 `opentalking/models/`，需要按改动范围额外运行更精确的 `ruff check` 和 pytest。

## 测试选择

按改动选择最小但有效的验证：

| 改动范围 | 建议验证 |
| --- | --- |
| 配置和 backend resolver | `pytest tests/unit/test_model_config.py tests/unit/test_omnirt_url.py apps/api/tests/test_models.py -v` |
| API route / schema | `pytest apps/api/tests -v` |
| task consumer / speak pipeline | `pytest tests/unit/test_task_consumer.py tests/unit/test_render_pipeline.py -v` |
| QuickTalk local adapter | `pytest tests/unit/test_quicktalk_adapter.py tests/frontend/test_quicktalk_send_path.py -v` |
| Wav2Lip local adapter | `pytest tests/unit/test_wav2lip_adapter.py tests/unit/test_wav2lip_metadata.py tests/unit/test_wav2lip_preload.py -v` |
| TTS provider | `pytest tests/unit/test_tts_factory.py tests/unit/test_edge_tts_adapter.py apps/api/tests/test_tts_preview.py -v` |
| 前端类型或 API 交互 | `cd apps/web && npm run typecheck && npm run build` |
| 文档结构或 API 文档 | `python scripts/docs/check_i18n_structure.py` 和 `python scripts/docs/check_api_docs.py` |

真实 LLM、TTS、STT、OmniRT、GPU/NPU、模型权重相关验证受本地环境限制。缺少依赖、密钥、模型权重或硬件时，要把它报告为环境阻塞，不要推断为 PR 代码必然错误。

## 文档要求

写文档时先说明读者和目标，再给命令。不要把叙事写成抽象产品介绍。

必须做到：

- 命令可复制，标明执行目录。
- 明确区分 mock、local、direct_ws、OmniRT、生产部署。
- 明确写出关键环境变量和默认值来源。
- OpenTalking 与 OmniRT 职责分开写，不要把 OmniRT worker / runtime 细节写成 OpenTalking 内部能力。
- 涉及模型路线时同步 README、`docs/zh/model-deployment/*`、`docs/en/model-deployment/*`。
- 涉及开发者接口时同步 `docs/zh/docs/*`、`docs/en/docs/*`。
- 涉及 API shape 时同步 `docs/*/docs/api/*` 或 API reference，并运行 docs 检查脚本。
- 示例不要包含真实密钥、私有 IP、绝对个人路径或不可公开的模型下载地址。
- 权重、缓存、生成视频、上传头像等大文件只说明放置路径，不提交进仓库。
- 如果中英文不同步是有意的，必须在 PR 说明中列出原因和后续任务。

避免：

- 使用旧路径 `src/opentalking/...`。
- 把 `OMNIRT_ENDPOINT` 写成所有模型都需要的必填项。
- 把 `quickstart` 旧脚本写成唯一推荐入口。
- 把配置默认值写死而不提示 `configs/default.yaml` 和环境变量会覆盖。
- 用“支持某模型”替代具体 backend、权重目录、启动命令和验证端点。

## 代码协作规则

保持改动小而准。不要顺手重构无关模块，不要格式化整仓，不要改动用户未要求的文档叙事。

修改配置、backend、模型适配时：

- 先读 `opentalking/core/model_config.py`、`opentalking/providers/synthesis/backends.py`、`opentalking/providers/synthesis/availability.py`。
- 新增本地模型 adapter 放在 `opentalking/models/<name>/`，并通过 `opentalking/models/registry.py` 注册。
- 远端模型不要伪装成本地 adapter；优先接入 `omnirt` 或 `direct_ws`。
- API 可用性状态要给出可诊断 reason，例如 `not_configured`、`omnirt_unavailable`、`local_adapter_missing`。
- 会话 API、前端模型选择器和 `/models` 状态要保持一致。

修改前端时：

- 遵守当前 React + Vite + TypeScript 结构。
- API client 优先改 `apps/web/src/lib/`，共享类型优先改 `apps/web/src/types.ts`。
- 保持 WebUI 是工作台，不要改成营销页。
- 用户可见交互变更要验证 `npm run typecheck` 和 `npm run build`。

修改脚本时：

- 保持 macOS / Linux shell 兼容。
- 不要静默占用已有端口；参考 `scripts/quickstart/_helpers.sh` 的端口检查。
- 不要把个人机器路径、临时 token、内网 host 写成默认值。

## PR / Review 规则

review 时只评价 PR 实际新增或修改的代码。先看：

```bash
git diff --stat
git diff --name-only
git diff
```

如果 PR 标题只覆盖部分内容，但 diff 同时改了 QuickTalk、MuseTalk、文档或脚本，要按子系统分组，不要把 unrelated 变更混成一个结论。验证失败时保留原始错误，例如 `ModuleNotFoundError: No module named 'pydantic_settings'`，并判断是环境问题还是代码问题。

提交前检查：

- `git status --short` 只包含本任务相关文件。
- 对应 pytest / ruff / npm / docs 检查已运行，或说明无法运行的具体原因。
- 文档和代码描述一致，尤其是启动命令、端口、backend、环境变量。
- 没有提交 `.env`、密钥、权重、缓存、生成媒体、大型二进制。

## OmniRT 协作提示

当任务跨到 sibling OmniRT 仓库时，先切换目录并读它自己的 README：

```bash
cd <omnirt-repo>
git status --short
sed -n '1,220p' README.md
```

OmniRT 当前重点是数字人链路的多模态推理框架，代码在 `src/omnirt/`，模型服务和 legacy wrapper 在 `model_backends/`，常用验证是：

```bash
pip install -e '.[dev]'
pytest
omnirt models
```

需要 HTTP 服务时按 OmniRT 文档安装 `.[server]`；需要真实 runtime 时按具体模型安装 `.[runtime]`、`.[wav2lip-cuda]`、`.[quicktalk-cuda]`、`.[fasterliveportrait]` 等 extra。OpenTalking 侧只依赖 OmniRT 暴露的 endpoint、模型列表和 audio2video WebSocket 协议。

跨仓修改要分别报告两个仓库的状态、验证命令和未验证原因。
