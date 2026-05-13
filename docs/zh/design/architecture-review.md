# 架构现状审查与重构建议

!!! abstract "TL;DR"
    2026-05-07 的架构现状评审。结论：当前分层不清晰、能力边界模糊；按持续增 STT/TTS/数字人合成/形象管理的演进路径会越来越难维护。提出的目标布局是 `opentalking/{core,providers,media,avatar,voice,pipeline,runtime}`，合成统一走 OmniRT。后续落地由 [Refactor 2026-05-07](../roadmap/refactor-2026-05-07.md) 推进。

!!! note "归档说明"
    本文是某个时点的快照（2026-05-07）。仓库当前结构可能已经在朝目标演进，最新概览请看 [架构](architecture.md)。

> 时间：2026-05-07
> 范围：仓库根目录 / `src/opentalking` / `apps` / `configs` / `docker` / `examples` / `demo`
> 目标：为 STT、TTS、数字人合成、数字人形象管理等全链路的持续演进建立清晰的分层架构

结论先行：**当前结构可以工作，但分层不清晰、能力边界模糊、模型/资产/代码/示例媒体相互渗透。**按持续增 STT/TTS/数字人合成/形象管理 + 前端的演进路径，会越来越难维护。

---

## 一、当前结构的核心问题

### 1. 代码物理位置矛盾（apps vs src 双轨）

- `apps/api/` 与 `src/opentalking/server/`（含 `_legacy.py`、`ws_server.py`、`runtime.py`）职责重叠：HTTP 入口/会话运行时同时存在两套。
- `apps/cli/` 与 `src/opentalking/cli/` 文件几乎重名（`download_models.py` / `generate_video.py` / `gradio_app.py`）—— 迁移没收尾的痕迹。
- `apps/worker/` 只剩 `tests/`，真正的 Worker 实现在 `src/opentalking/worker/`，`pyproject.toml` 也是这么指向的（`opentalking.worker.main:main`），与 `apps/` 命名给人的预期相反。
- 根目录 `multitalk_utils.py`（约 26K 行）显然是从外部 fork 拷过来未归位的资产。

### 2. "模型 / 推理引擎 / 资产" 三层混杂

- `src/opentalking/models/` 里既有**数字人合成模型适配器**（flashtalk、musetalk、wav2lip、flashhead 的 client/adapter），也有**算子级实现**（`face_detection.py`、`feature_extractor.py`、`network.py`、`layers.py`）。
- `src/opentalking/engine/`（WAN/MultiTalk attention/diffusion）实际上是 **FlashTalk 的内部推理实现**，但跟 `models/flashtalk/` 平级——FlashTalk 的代码被劈成两半放在两个顶层包里，且不通过任何抽象层。
- "与推理框架解耦"目标下，目前 WAN/xDiT/torch-npu/USP 等概念是直接散布在 `engine/` 中的，**没有 backend 抽象**。

### 3. 资产种类没有命名学

当前出现的"资产"至少有 5 类，但目录命名没有区分：

| 资产类型 | 当前位置 | 问题 |
|---|---|---|
| 模型权重（FlashTalk 14B / MuseTalk / Wav2Lip / Wav2Vec2） | `download_models.sh` 拉到运行时目录 | 没在仓库里抽象 |
| 数字人形象资产（reference.png / frames / manifest） | `examples/avatars/` | 跟"示例"混淆，生产形象不知放哪 |
| 语音克隆资产 | `voices/store.py` 运行时管理 | OK，但缺 schema 与 examples |
| 演示媒体（mp4、png） | 根目录 `demo/` ❌ + `images/` | 散落、且未 .gitignore |
| 示例代码 | `examples/avatars` | 和"avatar 示例资产"含义重叠 |

### 4. 提供方（providers）抽象缺失

- TTS 已经有 `tts/factory.py` + `tts/providers.py`，相对成熟。
- **STT 只有一个**（`stt/dashscope_asr.py`），没有 factory/registry，扩展第二家会重复 TTS 走过的路。
- **LLM** 同上：直接耦合到 `openai_compatible.py` + `conversation.py`，没有 provider 接口。
- **RTC** 只有 `aiortc_adapter.py`。
- 模型有 `models/registry.py`，但 STT/LLM/RTC 没对齐。**没有统一的 "Provider 注册 + 配置驱动" 模式**。

### 5. Worker 内部已经过载

- `flashtalk_runner.py` **2528 行**，`session_runner.py` **967 行**，`task_consumer.py` **504 行**。
- worker 同时承担了：任务消费、会话生命周期、TTS 流编排、模型推理调用、WebRTC 推流、录制导出、空闲帧生成。**典型"业务编排 + 适配 + I/O"全混的上帝模块**。

### 6. 配置文件分散

- 根 `configs/`（default.yaml、flashtalk.yaml、examples/）
- `src/opentalking/configs/`（flashtalk.yaml + models/*.yaml）
- `src/opentalking/engine/configs/`（wan_multitalk_14B.py）
- 根 `.env`、`.env.example`、`.env.flashtalk.example`、`.env.local.example`
- 同名 `flashtalk.yaml` 在 `configs/` 和 `src/opentalking/configs/` 各一份——**不知谁覆盖谁**。

### 7. 接口定义未充分使用

`src/opentalking/core/interfaces/`（avatar_asset / llm_adapter / model_adapter / render_session / tts_adapter）已经存在，**但 stt 没有接口，且 worker 里的具体实现有多大比例真的依赖这些接口需要审计**——目前看是建好了门、但没强制走。

### 8. 测试目录碎片化

`tests/unit/` + `apps/api/tests/` + `apps/worker/tests/` 三处，没有顶层 `integration/` `e2e/`。

---

## 二、核心架构决策

经讨论确认以下关键决策（影响后续所有分层）：

0. **无前向兼容包袱**：项目当前无外部用户，本次重构**直接采用最终目标结构**，旧链路（`engine/`、本仓内本地推理代码、`OPENTALKING_FLASHTALK_MODE` 等）全部删除，不留 deprecation 层。
1. **能力扁平化**：synthesis（数字人合成）与 STT/TTS/LLM/RTC 同级，统一归入 `providers/`。本质都是"对接外部推理服务"。
2. **avatar = 数字人聚合根**：不再是单纯"形象资产"，而是 `identity + appearance + voice + brain` 的聚合配置（manifest 引用其他资产）。
3. **voice 拆分**：声音复刻（cloning）作为推理能力放进 `providers/tts/<vendor>/clone.py`；`packages/voice/` 仅做资产管理。
4. **不在仓库内承担本地推理**：musetalk / wav2lip / wav2vec2 / FlashTalk 全部委托给推理服务（omnirt 为本月主路径）。**推理框架成为 opentalking 的运行时依赖**，仓库不再承载模型权重与本地推理代码。
5. **顶层去 `models/`**：删除根目录 `models/`，权重由推理框架自行管理与部署。
6. **统一 `.env.example`**：顶层一份权威模板，分组注释；部署形态差异走 `configs/profiles/*.yaml`。
7. **一键部署脚本**：`deploy/scripts/up.sh` 一次拉起【推理服务（omnirt）+ 后端（api/worker）+ 前端（web）+ Redis】。

---

## 三、建议的目标分层

```
opentalking/
├── .env.example                   # ⓪ 唯一权威环境变量模板（分组注释）
│
├── apps/                          # ① 部署单元（各自入口 / Dockerfile / 依赖切面）
│   ├── api/                       # FastAPI 进程：HTTP/SSE/转发
│   ├── worker/                    # 业务编排 Worker：消费队列 → 调 providers → 推 RTC
│   ├── unified/                   # 单进程合体（开发 / demo）
│   ├── gateway/                   # （可选）后续抽出的 RTC/SFU
│   └── web/                       # 前端
│
├── opentalking/                   # ② 可复用库代码（flat layout，根目录直接 import）
│   ├── core/                      # 协议 / 类型 / 事件 / 接口 / 配置 / Bus
│   │   ├── interfaces/            # 所有 Adapter Protocol（stt / tts / llm / rtc / synthesis）
│   │   ├── types/                 # frames / events / session / avatar 数据类
│   │   └── registry.py            # 统一 provider 注册器（装饰器 + 字符串 key 选择）
│   │
│   ├── providers/                 # ③ 所有外部能力（"能力域 / 提供方"两级）
│   │   ├── stt/dashscope/
│   │   ├── tts/
│   │   │   ├── edge/
│   │   │   ├── dashscope_qwen/
│   │   │   │   ├── adapter.py
│   │   │   │   └── clone.py       # 声音复刻：同 SDK 紧凑落位
│   │   │   ├── dashscope_sambert/
│   │   │   ├── cosyvoice_ws/
│   │   │   └── elevenlabs/
│   │   ├── llm/openai_compatible/
│   │   ├── rtc/aiortc/
│   │   └── synthesis/             # ★ 与 STT/TTS 同级，全部为 thin client
│   │       ├── flashtalk/         # 接 omnirt / 自建 FlashTalk 服务
│   │       ├── flashhead/
│   │       └── omnirt.py          # OmniRTSynthesisAdapter（注册为 musetalk/wav2lip/flashtalk 三键）
│   │
│   ├── media/                     # ④ 中性算子工具：loudness、frame compose、idle frame、face crop
│   ├── avatar/                    # ⑤ 数字人聚合根：identity + appearance + voice + brain
│   ├── voice/                     # ⑥ 仅资产管理（voice_id 索引、样本、与 avatar 的引用）
│   ├── pipeline/                  # ⑦ 业务编排：session / speak / recording
│   └── runtime/                   # ⑧ 进程级胶水：task_consumer / bus / timing / main
│
├── assets/                        # ⑨ 仓库内**示例**数字人 / 音色（manifest 占位为主，重资产走 LFS）
│   ├── avatars/
│   │   ├── flashtalk-demo/
│   │   ├── musetalk-demo/
│   │   └── customer-service-anna/
│   └── voices/
│
├── configs/                       # ⑩ 唯一配置中心
│   ├── default.yaml
│   ├── profiles/                  # 部署形态：cloud-only / self-hosted-omnirt / unified-dev
│   ├── providers/                 # 各 provider 的可调参数
│   └── inference/                 # 推理服务（omnirt / vllm）的接入端点配置
│
├── deploy/                        # ⑪ 部署相关全部归位（含一键拉起）
│   ├── docker/                    # 各服务 Dockerfile
│   ├── compose/                   # docker-compose（含 omnirt + redis + api + worker + web）
│   └── scripts/
│       ├── up.sh                  # ★ 一键拉起：推理服务 + 后端 + 前端 + Redis
│       ├── down.sh
│       └── prepare-avatar.sh
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docs/
└── pyproject.toml                 # 工作区（uv workspaces / hatch 可选）
```

### Avatar manifest 形态（参考）

```yaml
# assets/avatars/customer-service-anna/manifest.yaml
id: customer-service-anna
identity:
  display_name: "Anna"
  persona_prompt: "你是一名银行客服..."
appearance:
  reference_image: ./reference.png
  frames: ./frames/                     # 可选
  synthesis:
    provider: flashtalk                 # 选 providers/synthesis/* 之一
    endpoint_ref: inference.flashtalk   # 引用 configs/inference/*.yaml
    params: { sampling_steps: 8 }
voice:
  ref: voices/anna-clone-v2             # 引用 packages/voice 中资产
  tts:
    provider: cosyvoice_ws
    params: { speed: 1.0 }
brain:
  llm:
    provider: openai_compatible
    model: qwen2.5-72b-instruct
    params: { temperature: 0.7 }
behavior:
  idle_action: subtle_blink
  interrupt_strategy: graceful
```

---

## 四、最关键的 7 条解耦原则（持续演进的护栏）

1. **能力域扁平化**：`providers/{stt,tts,llm,rtc,synthesis}` 全部同级，新增能力不再特殊对待。
2. **唯一 Provider 注册表**：`core/registry.py` + 装饰器注册，`configs/*.yaml` 字符串 key 选择。**业务代码禁止 import 具体 provider 实现**。
3. **推理框架是依赖、不是仓库内代码**：FlashTalk / MuseTalk / Wav2Lip 等本地推理代码全部移除，仓库内只保留对接 omnirt / vllm 的 client。模型权重不进 git，由推理框架自行管理。
4. **avatar 是聚合根**：所有"一个数字人"的描述（identity / appearance / voice / brain / behavior）汇于一份 manifest，引用 voice / inference / provider 的稳定 key。
5. **voice 严格拆分**：克隆能力进 `providers/tts/<vendor>/clone.py`，资产管理留在 `packages/voice/`。
6. **Worker 是 pipeline 的宿主**：`flashtalk_runner.py` 2528 行按"音频流→合成调用→编码→推流"切片，runner 内不留模型实现。
7. **单一配置源**：`src/opentalking/configs` 和 `configs/` 不再双源；`engine/configs/wan_multitalk_14B.py` 这种"Python 当配置"全部迁出（如本就属于推理框架，则随推理代码一并移除）。

---

## 五、执行顺序（一次到位，无前向兼容包袱）

> **背景**：项目当前无外部用户，本次重构直接采用最终目标结构，**不为旧代码留兼容层**。
> 旧链路（`engine/`、本仓内 FlashTalk 本地推理、`OPENTALKING_FLASHTALK_MODE` 等）一并删除。

### 阶段 1：清理 + 砍掉本地推理（半天）
- 删 `apps/cli/`（保留 `src/opentalking/cli/` 或反之，二选一）。
- 删 `apps/worker/` 空壳。
- 删根目录 `multitalk_utils.py` / `demo/` / `images/` 中非文档图 / 三份 `.env.*.example` / 顶层 `models/` 目录（如已存在）。
- 删 `src/opentalking/engine/` **整体目录**。
- 删 `src/opentalking/models/{flashtalk,musetalk,wav2lip}/` 中所有本地推理文件（`network.py` / `inference.py` / `face_detection.py` / `feature_extractor.py` / `layers.py` / `model_defs.py` / `audio.py` / `loader.py` 等），仅保留 client 部分（迁入新位置）。
- 删 `src/opentalking/configs/` 整个目录（与根 `configs/` 双源）。
- 删 `download_models.sh` 中本地推理权重相关下载（仅保留 omnirt 不负责的、本仓自己用的轻量资源，如有）。
- 删 `OPENTALKING_FLASHTALK_MODE=local|remote|off` 配置项与所有 fallback 分支。
- `pyproject.toml` 同步删除 `engine` extra 中的 torch / xfuser / xdit 等推理依赖。

### 阶段 2：目录搬家到目标结构（1–2 天）
直接落地 § 三的目标分层：
- 建 `opentalking/{core,providers,media,avatar,voice,pipeline,runtime}/` 全套骨架。
- 现有 STT/TTS/LLM/RTC 适配器迁入 `providers/<能力>/<vendor>/`，对齐 `core/registry.py` 装饰器注册。
- 新增 `providers/synthesis/`：单一 `OmniRTSynthesisAdapter` + 三个 provider key 注册（flashtalk / musetalk / wav2lip）。
- `voices/bailian_clone.py` 移入 `providers/tts/dashscope/clone.py`；`voices/store.py` 移入 `packages/voice/store.py`。
- `apps/api/` 与 `src/opentalking/server/` 合并为 `apps/api/`，删除 `_legacy.py`。

### 阶段 3：avatar 聚合根 + pipeline 重写（3–5 天）
- 实现 `packages/avatar/{manifest,store,validator,assemble,loader}.py`，schema 按 § 七.5 终态。
- 实现 `FilesystemAvatarStore`（builtin `assets/avatars/` + user `var/avatars/`）。
- 拆 `flashtalk_runner.py` 2528 行 → `packages/pipeline/speak/{audio,synthesis,encode,push}.py`，**不保留 FlashTalk 专属命名**，所有合成走 SynthesisAdapter 接口。
- 拆 `session_runner.py` 967 行 → `packages/pipeline/session/runner.py`。
- `task_consumer.py` 504 行 → `packages/runtime/task_consumer.py`。

### 阶段 4：一键部署（2–3 天）
- `deploy/compose/`：cuda / ascend / cpu / dev 四份 compose（omnirt + redis + api + worker + web）。
- `deploy/scripts/`：`install.sh` / `install_native.sh` / `install_docker.sh` / `up.sh` / `down.sh` / `detect_hardware.sh` / `ensure_omnirt.sh` / `download_flashtalk.sh`。
- `configs/inference/omnirt.yaml`：端点 + 任务面 + 模型映射。
- `configs/profiles/{cuda-3090,cuda-4090,ascend-910b,cpu-demo}.yaml`。

### 阶段 5：测试与文档（2–3 天）
- 测试合并到顶层 `tests/{unit,integration,e2e}/`，删 `apps/api/tests`、`apps/worker/tests` 残留。
- README / quickstart / deployment / configuration / avatar-format / hardware 同步重写（详见 § 九）。
- 删 `docs/flashtalk-omnirt.md`（omnirt 已是默认路径，无独立文档必要）。

**总周期**：约 8–13 天。建议在 Week 1 内推进 **阶段 1+2+4 的最小版本**（保证 5/7 端到端跑通），阶段 3+5 在 Week 2 完成（配合 UI 演进）。

---

## 六、问题清单速览（可作为 backlog）

### 物理清理
- [ ] `apps/cli` ↔ `src/opentalking/cli` 重复
- [ ] `apps/api` ↔ `src/opentalking/server` 职责重叠 + `_legacy.py` 残留
- [ ] `apps/worker/` 空壳与 `src/opentalking/worker/` 命名不一致
- [ ] 根目录 `multitalk_utils.py` 未归位（26K 行）
- [ ] 根目录 `demo/` 媒体文件入仓
- [ ] `images/` 中非文档图未归位
- [ ] 三份 `.env.*.example` 收敛为一份 `.env.example`

### 推理框架解耦（核心）
- [ ] `src/opentalking/engine/` 整体迁出（FlashTalk 本地推理）
- [ ] `src/opentalking/models/{flashtalk,musetalk,wav2lip}/` 仅保留 client，移除本地推理代码
- [ ] 顶层 `models/` 目录及 `download_models.sh` 移除
- [ ] 推理框架（omnirt / vllm）以服务形式接入，docker-compose 一键拉起

### Provider 体系
- [ ] STT/LLM/RTC 缺 provider 接口与注册器
- [ ] 新增 `providers/synthesis/`（与 STT/TTS 同级）
- [ ] TTS provider 内嵌 cloning（`providers/tts/<vendor>/clone.py`）
- [ ] 统一 `core/registry.py` 装饰器注册模式

### 资产与配置
- [ ] avatar 升级为聚合根 manifest（identity + appearance + voice + brain + behavior）
- [ ] `voices/bailian_clone.py` 推理逻辑迁至 `providers/tts/dashscope_*/clone.py`
- [ ] `packages/voice/` 收回为纯资产管理
- [ ] `configs/` 与 `src/opentalking/configs/` 双源消除
- [ ] `engine/configs/wan_multitalk_14B.py`（Python 当配置）随推理代码迁出
- [ ] `configs/inference/` 落地推理服务端点配置

### Worker 拆分
- [ ] `flashtalk_runner.py` 2528 行 → `pipeline/speak/` 多文件
- [ ] `session_runner.py` 967 行 → `pipeline/session/`
- [ ] `task_consumer.py` 504 行 拆分

### 测试与部署
- [ ] 测试目录三处分散（`tests/unit` + `apps/api/tests` + `apps/worker/tests`）合并
- [ ] `deploy/scripts/up.sh` 一键拉起脚本
- [ ] `deploy/compose/` 完整编排（omnirt + redis + api + worker + web）
- [ ] `core/interfaces/` 已建但未强制使用
- [ ] 形象/音色资产没有"生产 vs 示例"的物理隔离
- [ ] 模型权重缺仓库内 manifest（仅靠 `download_models.sh` 脚本）

---

## 七、用户配置 → 运行链路（数据与模块流转）

> 场景：用户在前端选择内置/自定义数字人 → 上传图 → 选模型/音色/角色 prompt → 点击"开始对话"。

### 7.1 两层数据模型（必须严格区分）

```
┌─────────────────────────────────────────────────────────────────┐
│  AvatarProfile（声明式 / 可持久化 / 字符串 ref）                │  ← 用户编辑的对象
│  - identity / appearance / voice / brain / behavior              │
│  - 引用 provider key、voice_id、inference endpoint，不持有任何   │
│    运行态对象                                                    │
└────────────────────────────┬────────────────────────────────────┘
                             │  avatar.assemble()
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  ResolvedDigitalHuman（运行态 / 含具体适配器实例）              │  ← Pipeline 消费
│  - synthesis: SynthesisAdapter 实例（已绑定 omnirt 端点）        │
│  - tts: TTSAdapter 实例（已绑定 voice_id）                      │
│  - llm: LLMAdapter 实例（已注入 persona prompt）                │
│  - appearance_assets: 已加载的参考图 / frames                   │
└─────────────────────────────────────────────────────────────────┘
```

**核心原则**：前端只动第一层；pipeline 只消费第二层；中间由 `avatar.assemble` 桥接。

### 7.2 模块职责

| 阶段 | 模块 | 职责 |
|---|---|---|
| **能力发现** | `providers/*` + `core/registry.py` | 注册所有 STT/TTS/LLM/synthesis 实现 |
|  | `apps/api/routes/catalog.py`（新增） | `GET /catalog/synthesis` / `GET /catalog/tts` / `GET /catalog/voices` —— 前端拉下拉框选项 |
| **用户编辑** | `apps/web` | 表单 UI：选模型 / 选音色 / 写 prompt / 上传图 |
|  | `apps/api/routes/avatars.py` | `POST /avatars` 创建 / `PATCH /avatars/{id}` / `POST /avatars/{id}/appearance` 上传 |
|  | `apps/api/services/avatar_service.py` | 入参校验、调用 store、写入 profile |
| **资产持有** | `packages/avatar/` | **AvatarProfile schema + store + validator + assemble** |
|  | `packages/voice/` | voice_id 索引、试听文件、与 avatar 的引用 |
| **运行装配** | `packages/avatar/assemble.py` | profile → ResolvedDigitalHuman（核心解析器） |
| **运行编排** | `packages/pipeline/session/` | 接 ResolvedDigitalHuman，编织 STT→LLM→TTS→Synthesis→RTC |
| **能力执行** | `providers/*` | 无状态适配器，不关心 avatar 概念 |

### 7.3 关键调用链（点击"开始对话"）

```
[Web]  POST /sessions { avatar_id }
   │
   ▼
[apps/api]  routes/sessions.py
   │  ① 查 AvatarProfile  → packages/avatar/store.get(avatar_id)
   │  ② 校验运行可达性    → packages/avatar/validator.check_runtime(profile)
   │                          - synthesis provider 注册存在？
   │                          - omnirt 端点健康？
   │                          - voice_id 在 voice store 存在？
   │  ③ 写会话 + RPUSH init 到 Redis
   ▼
[apps/worker]  pipeline/session/runner.py
   │  ④ BRPOP init，含 avatar_id
   │  ⑤ resolved = avatar.assemble(profile)        ← 桥接点
   │       │
   │       ├─ synthesis = registry.get("synthesis", profile.appearance.synthesis.provider)
   │       │             .bind(endpoint=configs/inference/<ref>.yaml)
   │       ├─ tts       = registry.get("tts", profile.voice.tts.provider)
   │       │             .bind(voice_id=voice.store.resolve(profile.voice.ref))
   │       ├─ llm       = registry.get("llm", profile.brain.llm.provider)
   │       │             .with_system_prompt(profile.identity.persona_prompt)
   │       └─ appearance = appearance_loader.load(profile.appearance)
   │  ⑥ pipeline/speak 用 resolved 跑 STT→LLM→TTS→synthesis→RTC
   ▼
[providers/*]  纯能力执行
```

### 7.4 Profile 存储（采用方案 A：文件系统）

> 单机部署起步，预留 `AvatarStore` 协议，后续切 DB 不动业务代码。

布局：

```
assets/avatars/                # 仓库内置（go with repo / docker image）
  flashtalk-demo/
    manifest.yaml
    reference.png
  customer-service-anna/
    manifest.yaml
    reference.png
    frames/

var/avatars/                   # 用户运行时创建（gitignore）
  user-<uuid>/
    manifest.yaml
    reference.png              # 用户上传的原图
    derived/                   # 装配过程产出（face crop / preview）
```

`AvatarStore` 接口（位于 `packages/avatar/store.py`）：

```python
class AvatarStore(Protocol):
    def list(self, scope: Literal["builtin", "user", "all"]) -> list[AvatarSummary]: ...
    def get(self, avatar_id: str) -> AvatarProfile: ...
    def create(self, profile: AvatarProfile, files: dict[str, BinaryIO]) -> str: ...
    def update(self, avatar_id: str, patch: AvatarProfilePatch) -> None: ...
    def delete(self, avatar_id: str) -> None: ...

class FilesystemAvatarStore(AvatarStore):
    def __init__(self, builtin_dir: Path, user_dir: Path): ...
```

### 7.5 Avatar manifest 形态

```yaml
# var/avatars/<id>/manifest.yaml
id: customer-service-anna
identity:
  display_name: "Anna"
  persona_prompt: "你是一名银行客服..."
appearance:
  reference_image: ./reference.png
  frames: ./frames/                     # 可选
  synthesis:
    provider: flashtalk                 # → providers/synthesis/flashtalk
    endpoint_ref: omnirt.flashtalk      # → configs/inference/omnirt.yaml#flashtalk
    params: { sampling_steps: 8 }
voice:
  ref: voices/anna-clone-v2             # → packages/voice store
  tts:
    provider: cosyvoice_ws
    params: { speed: 1.0 }
brain:
  llm:
    provider: openai_compatible
    model: qwen2.5-72b-instruct
    params: { temperature: 0.7 }
behavior:
  idle_action: subtle_blink
  interrupt_strategy: graceful
```

### 7.6 catalog API（前端下拉框驱动）

```
GET /catalog/synthesis     → [{ key: "flashtalk", display: "FlashTalk 14B", endpoints: [...] }, ...]
GET /catalog/tts           → [{ key: "cosyvoice_ws", display: "CosyVoice", voice_count: 12 }, ...]
GET /catalog/llm           → [...]
GET /catalog/voices        → [{ id: "anna-clone-v2", name: "Anna", preview_url: ... }, ...]
GET /catalog/personas      → 内置性格预设
```

来源：`core/registry.py` 自动汇聚 + `configs/inference/*.yaml` 端点元数据。**新接一个 provider，前端下拉框自动多一项**。

---

## 八、Week 1 (5/1-5/7) 工程 1（Infra）落地计划

> 与本架构调整对齐的具体执行方案。原则：**Week 1 交付物在新架构方向上不留债，但不要求阶段 1（迁出本地推理代码）当周完成**。

### 8.1 设计原则（Week 1 必须遵守）

1. **omnirt 唯一推理路径**：FlashTalk / MuseTalk / Wav2Lip 全部走 [omnirt](https://github.com/datascale-ai/omnirt)；本仓内**不再有任何本地推理代码**。
2. **install.sh 是入口，compose 是核心**：用户实际运行的是 docker-compose；install.sh 只做硬件探测 + 选 profile + 调 compose。
3. **profile 统一文件**：单一 `.env.example` + `configs/profiles/*.yaml` + `configs/inference/omnirt.yaml`，三者职责正交。
4. **新结构落地优先**：Week 1 直接以 § 三 目标分层为准搬家，**不保留旧目录与旧 ENV 变量**（无外部用户，无兼容包袱）。

### 8.2 交付物清单（按优先级）

#### A. 推理服务集成（omnirt）—— P0

```
deploy/
├── compose/
│   ├── docker-compose.cuda.yml         # omnirt + redis + api + worker + web
│   ├── docker-compose.ascend.yml       # omnirt-ascend + ...
│   ├── docker-compose.cpu.yml          # 仅 light models（如 omnirt 提供 cpu image）
│   └── docker-compose.dev.yml          # 单进程 unified（无 omnirt，前端联调用）
└── scripts/
    ├── install.sh                      # 顶层入口
    ├── install_native.sh               # pip + venv 路径
    ├── install_docker.sh               # docker pull + compose up 路径
    ├── detect_hardware.sh              # 输出 cuda-3090 / cuda-4090 / ascend-910b / cpu
    ├── up.sh                           # 一键拉起（含健康检查）
    ├── down.sh
    ├── download_flashtalk.sh           # FlashTalk 14B 权重独立下载（37GB，按需）
    └── ensure_omnirt.sh                # pull / start omnirt 镜像，等待 /health
```

`install.sh` 流程：

```bash
#!/usr/bin/env bash
set -e
profile=$(scripts/detect_hardware.sh)               # → cuda-4090
mode=${1:-docker}                                   # docker | native
echo "Detected: $profile, install mode: $mode"

case $mode in
  docker)  bash scripts/install_docker.sh "$profile" ;;
  native)  bash scripts/install_native.sh "$profile" ;;
esac

# 默认拉轻量权重；4090/910B 询问是否同时拉 FlashTalk
if [[ "$profile" =~ ^(cuda-4090|ascend-910b)$ ]]; then
  read -p "Detected high-end hardware. Download FlashTalk 14B (37GB)? [y/N] " yn
  [[ "$yn" == "y" ]] && bash scripts/download_flashtalk.sh
fi

bash scripts/up.sh "$profile"
echo "✅ OpenTalking is up at http://localhost:8000"
```

`up.sh` 健康检查链：

```
1. compose up -d redis
2. compose up -d omnirt          → curl localhost:9000/health (max 60s)
3. compose up -d api worker       → curl localhost:8000/health
4. compose up -d web              → curl localhost:5173
5. 打印 console URL + sample avatar id
```

#### B. 配置三件套（无歧义来源）—— P0

```
.env.example                            # 唯一权威（顶层）
configs/
├── default.yaml
├── profiles/
│   ├── cuda-3090.yaml                  # 默认 musetalk / wav2lip
│   ├── cuda-4090.yaml                  # 默认 musetalk，可选 flashtalk
│   ├── ascend-910b.yaml                # 默认 flashtalk
│   └── cpu-demo.yaml                   # 只有 wav2lip
├── inference/
│   └── omnirt.yaml                     # endpoint 列表 + 任务面映射
└── synthesis/
    ├── flashtalk.yaml
    ├── musetalk.yaml
    └── wav2lip.yaml
```

`.env.example`（分组示例）：

```
# === Service ===
OPENTALKING_HARDWARE_PROFILE=cuda-4090
OPENTALKING_API_PORT=8000
OPENTALKING_WEB_PORT=5173

# === Inference (omnirt) ===
OMNIRT_ENDPOINT=http://omnirt:9000
OMNIRT_API_KEY=
OMNIRT_DEFAULT_BACKEND=cuda

# === Storage ===
OPENTALKING_AVATARS_DIR=./var/avatars
OPENTALKING_VOICES_DIR=./var/voices
OPENTALKING_REDIS_URL=redis://redis:6379/0

# === STT ===
DASHSCOPE_API_KEY=

# === TTS ===
EDGE_TTS_DEFAULT_VOICE=zh-CN-XiaoxiaoNeural
COSYVOICE_WS_URL=

# === LLM ===
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=qwen2.5-72b-instruct

```

`configs/inference/omnirt.yaml`（avatar manifest 通过 `endpoint_ref` 引用）：

```yaml
endpoints:
  flashtalk:
    base_url: ${OMNIRT_ENDPOINT}
    task: audio2video
    model: soulx-flashtalk-14b
  musetalk:
    base_url: ${OMNIRT_ENDPOINT}
    task: audio2video
    model: musetalk-1.5
  wav2lip:
    base_url: ${OMNIRT_ENDPOINT}
    task: audio2video
    model: wav2lip
  cosyvoice:
    base_url: ${OMNIRT_ENDPOINT}
    task: streaming_tts
    model: cosyvoice-2.0
```

#### C. 旧代码删除 —— P0（无前向兼容包袱）

- [ ] 删 `apps/cli/` 和 `src/opentalking/cli/` 中的重复，二选一保留并更新 pyproject scripts。
- [ ] 删 `apps/worker/` 空壳目录。
- [ ] 删根目录 `multitalk_utils.py` / `demo/` / `images/` 中非文档图。
- [ ] 删三份 `.env.*.example`，新建顶层唯一 `.env.example`。
- [ ] 删 `src/opentalking/configs/`（双源），统一到根 `configs/`。
- [ ] **删 `src/opentalking/engine/` 整个目录**（FlashTalk 本地推理）。
- [ ] **删 `src/opentalking/models/{flashtalk,musetalk,wav2lip}/` 中的本地推理实现**，仅保留外部调用 client 部分（迁入 `providers/synthesis/`）。
- [ ] 删 `OPENTALKING_FLASHTALK_MODE` 配置项与所有相关 fallback 分支。
- [ ] `pyproject.toml` 的 `engine` extra 中 torch / xfuser / xdit / accelerate / diffusers 等推理依赖移除。
- [ ] 删 `apps/api/_legacy.py` 和 `src/opentalking/server/_legacy.py`。
- [ ] 删 `docs/flashtalk-omnirt.md`、`docs/flashtalk-omnirt.en.md`（合入 deployment.md）。

#### D. omnirt client（在最终目录直接落位）—— P0

`opentalking/providers/synthesis/omnirt.py`：

```python
class OmniRTSynthesisAdapter(SynthesisAdapter):
    """统一通过 omnirt 接入 flashtalk / musetalk / wav2lip 的 thin client."""
    def __init__(self, endpoint: OmnirtEndpoint, model: str): ...
    async def stream_audio_to_video(self, audio_chunks): ...

# 注册三个 alias，profile 选哪个就用哪个
register("synthesis", "flashtalk", lambda cfg: OmniRTSynthesisAdapter(cfg.endpoint, "soulx-flashtalk-14b"))
register("synthesis", "musetalk",  lambda cfg: OmniRTSynthesisAdapter(cfg.endpoint, "musetalk-1.5"))
register("synthesis", "wav2lip",   lambda cfg: OmniRTSynthesisAdapter(cfg.endpoint, "wav2lip"))
```

#### E. Hardware profile 框架 —— P1

`configs/profiles/cuda-4090.yaml`：

```yaml
hardware:
  vendor: nvidia
  device: cuda-4090
  vram_gb: 24
defaults:
  synthesis: musetalk          # 默认 musetalk，FlashTalk 可选
  tts: edge
  llm: openai_compatible
  stt: dashscope
fallback_chain:
  synthesis: [musetalk, wav2lip]
omnirt:
  backend: cuda
  required_models: [musetalk-1.5, wav2lip]
  optional_models: [soulx-flashtalk-14b]
```

`configs/profiles/ascend-910b.yaml`：

```yaml
hardware:
  vendor: huawei
  device: ascend-910b
defaults:
  synthesis: flashtalk
omnirt:
  backend: ascend
  required_models: [soulx-flashtalk-14b]
```

启动时 `apps/api/main.py` 打印：

```
Hardware profile: cuda-4090 (auto-detected)
  Synthesis: musetalk (via omnirt @ http://omnirt:9000)
  TTS:       edge
  LLM:       openai_compatible (qwen2.5-72b-instruct)
```

#### F. Avatar profile 文件系统（最小可用）—— P1

`packages/avatar/store.py` 实现 `FilesystemAvatarStore`：

```python
class FilesystemAvatarStore(AvatarStore):
    def __init__(
        self,
        builtin_dir: Path = Path("assets/avatars"),
        user_dir: Path = Path(os.getenv("OPENTALKING_AVATARS_DIR", "./var/avatars")),
    ): ...
```

Week 1 不要求 schema 完全终态，但必须：
- 解析 manifest.yaml（identity / appearance / voice / brain 五字段）
- API `GET /avatars` 列出 builtin + user
- API `POST /avatars` 接收图片 + manifest，落盘到 `var/avatars/`
- API `GET /avatars/{id}` 返回完整 profile（含 reference 图 URL）

### 8.3 Week 1 验收路径（5/7 端到端 demo）

```bash
# 在干净 Ubuntu 22.04 + 4090 上
git clone https://github.com/<org>/opentalking && cd opentalking
cp .env.example .env
bash scripts/install.sh docker
# → 自动 detect cuda-4090 → 选择 docker 路径
# → 拉镜像（omnirt + opentalking-api + worker + web + redis）
# → ensure_omnirt.sh 等待健康
# → up.sh 启动后端前端
# → 打开 http://localhost:5173
# 在前端：选择 "flashtalk-demo" → 选音色 edge-zh-XiaoXiao → 输入 persona prompt
# → 点击"开始对话" → 说话 → 视频播放
```

通过 = Week 1 验收通过。

### 8.4 Week 1 范围与延后项

**Week 1 内必须完成**（5/7 验收硬条件）：
- ✅ 阶段 1 全量删除（engine / 本地推理代码 / 旧 ENV / 旧文档）
- ✅ 阶段 2 目录搬家（providers / avatar / voice / pipeline 骨架就位）
- ✅ 阶段 4 一键部署（install.sh + compose + omnirt 起得来）
- ✅ 至少一条端到端链路跑通（musetalk via omnirt）

**Week 2 完成**（配合工程 3 UI 演进）：
- avatar manifest schema 终态 + assemble.py 完整化
- pipeline/speak 与 pipeline/session 充分拆分（阶段 3 收尾）
- catalog API + 前端下拉框联动

**Week 3+**：
- 多硬件 profile 自动切换 + benchmark CI
- Windows 支持 → 6 月

---

## 九、README 更新计划

> 调整后的 README 必须服务于"用户 5 分钟跑通"，与新架构（omnirt 推理 + 一键部署 + avatar profile）对齐。

### 9.1 当前 README 问题

- 仍以 FlashTalk 14B 为唯一卖点，门槛高（37GB 权重劝退）
- 部署说明分散在 quickstart / deployment / flashtalk-omnirt 多文档
- 没有 "选模型 / 选音色 / 选 prompt → 对话" 的 UX 叙事
- 没有 omnirt 依赖说明
- 截图/gif 缺失

### 9.2 新 README 章节结构（提案）

```markdown
# OpenTalking
> 实时陪伴型数字人开源框架 · 一键部署 · 自定义形象/音色/性格

[badge: stars] [badge: license] [badge: docker]

[30 秒 demo gif —— 选 avatar → 说话 → 数字人回应]

## ✨ 核心能力
- 🎭 **可配置数字人**：形象 / 音色 / 性格 / 技能四维度自定义
- ⚡ **实时交互**：< 2s 首响，支持中途打断
- 🔧 **多硬件**：3090 / 4090 / 910B / CPU 同一套架构
- 🎯 **分层模型**：默认轻量（数百 MB），可选高质量（FlashTalk 14B）
- 🔌 **解耦推理**：基于 [omnirt](https://github.com/datascale-ai/omnirt) 推理服务，替换/扩展模型零侵入

## 🚀 快速开始（3 行命令）
```bash
git clone https://github.com/<org>/opentalking && cd opentalking
cp .env.example .env                  # 按需填 STT/LLM 凭据
bash scripts/install.sh               # 自动探测硬件 + 拉起所有服务
```
打开 http://localhost:5173，选择内置 avatar 即可对话。

## 📐 架构总览
[architecture-v2 简图]

OpenTalking = 业务编排（本仓） + 推理服务（omnirt） + 前端控制台。
所有模型推理（FlashTalk / MuseTalk / Wav2Lip / TTS / 音色克隆）由 omnirt 承担。

## 🎨 自定义数字人
1. 进入"角色管理"→"新建"
2. 上传一张参考图（建议正面、肩部以上）
3. 选择合成模型（musetalk / flashtalk / wav2lip）
4. 选择音色（preset 或上传 30s 音频克隆）
5. 写角色 prompt（例："你是一个温柔的语言教师..."）
6. 保存 → 在主页选中 → 开始对话

## 🛠 部署形态
| 形态 | 命令 | 适用 |
|---|---|---|
| Docker（推荐） | `bash scripts/install.sh docker` | 生产 / 一键体验 |
| Native | `bash scripts/install.sh native` | 开发 / 想本地跑 |
| Unified（无 omnirt） | `docker compose -f deploy/compose/docker-compose.dev.yml up` | 前端联调 |

## 🖥 硬件 profile
（表格：cuda-3090 / cuda-4090 / ascend-910b / cpu-demo）

## 📚 文档
- [架构设计](https://github.com/datascale-ai/opentalking/blob/main/docs/architecture-review.md)
- [部署指南](https://github.com/datascale-ai/opentalking/blob/main/docs/deployment.md)
- [API 参考](https://github.com/datascale-ai/opentalking/blob/main/docs/api-reference.md)
- [Avatar manifest 规范](https://github.com/datascale-ai/opentalking/blob/main/docs/avatar-format.md)
- [硬件适配](https://github.com/datascale-ai/opentalking/blob/main/docs/hardware.md)

## 🔗 上下游
- 推理服务：[omnirt](https://github.com/datascale-ai/omnirt)
- Agent / 记忆：[OpenClaw](https://...)（可选）

## 🤝 贡献
[CONTRIBUTING / CODE_OF_CONDUCT 链接]

## 📄 License
Apache 2.0
```

### 9.3 README 配套文档更新清单

| 文档 | 动作 | 说明 |
|---|---|---|
| `README.md` / `README.en.md` | **重写** | 按 9.2 结构 |
| `docs/quickstart.md` | 重写 | 改为 omnirt-first，删除 FlashTalk 本地部署 |
| `docs/deployment.md` | 重写 | docker / native / k8s 三种形态 |
| `docs/architecture.md` | 更新 | 链接到 architecture-review.md，作为现状指针 |
| `docs/avatar-format.md` | 更新 | 同步新 manifest schema（identity/appearance/voice/brain/behavior） |
| `docs/hardware.md` | 更新 | 4 个 profile 详细说明 |
| `docs/configuration.md` | 重写 | `.env.example` 字段逐项说明 + 三件套关系 |
| `docs/flashtalk-omnirt.md` | **删除** | omnirt 是默认路径，无需独立文档 |
| `docs/local-dev.md` | 更新 | 新增"unified 单进程"开发说明 |
| `docs/model-adapter.md` | 改为"添加新 provider 指南" | 教用户接 STT/TTS/LLM/synthesis |
| `docs/render-pipeline.md` | 保留 | 但更新内部图，去掉 engine/ |

### 9.4 README 更新执行顺序（Week 1 内）

| 顺序 | 工作 | 责任 | 截止 |
|---|---|---|---|
| 1 | 写新 README 骨架 + .env.example 收敛 | 工程 1 | 5/3 |
| 2 | 录 30 秒 demo gif | 工程 3 + 宣传 | 5/6 |
| 3 | 部署文档 / 硬件 profile 表 / 配置说明 | 工程 1 | 5/6 |
| 4 | 中英 README 同步 + 截图嵌入 | 宣传 | 5/7 |
| 5 | 验收：清空环境 → 跟着 README 跑通 | 全员 | 5/7 |

**验收硬条件**：一个从未接触本项目的人，按 README 三行命令 + 前端点击，5 分钟内看到数字人说话。

