# OpenTalking 5 月演进计划（2026-05）

!!! abstract "TL;DR"
    2026 年 5 月的月度路线：完成架构 v2 迁移、wav2lip / musetalk / flashtalk 统一走 OmniRT、上线一键部署脚本和官方 Docker 镜像，Star 目标 1000–2000。

!!! note "归档说明"
    本文是 2026-05-01 制定的计划，时点性强。最新进度看 GitHub Issues / PR。

> 制定日期：2026-05-01
> 周期：2026-05-01 ~ 2026-05-30（4 周）
> 团队：3 工程师 + 1 兼职宣传/文档
> Star 目标：1000 - 2000（5/30 前）
> 产品定位：陪伴型实时数字人，支持多硬件（消费级 3090 / 4090 / Ascend 910B）可配置切换
> 上游依赖：外部仓 [datascale-ai/omnirt](https://github.com/datascale-ai/omnirt) 提供模型推理服务；OpenClaw 提供 Agent / Memory 能力

---

## 1. 总体策略

### 1.1 产品定位

OpenTalking 在本月明确定位为"**陪伴型实时数字人开源框架**"：

- **可配置的角色**：形象、音色、性格、技能（Skill）四维度均可由用户配置
- **多硬件适配**：3090 / 4090 / 910B 同一套架构，按硬件 profile 自动切换
- **分层模型策略**（首次体验门槛低，高质量按需升级）：
  - **轻量路径（默认）**：Wav2Lip / MuseTalk，权重数百 MB，3090 / 3060 / CPU 都能跑，install.sh 默认安装
  - **高质量路径（按需）**：FlashTalk 14B 需 37GB 权重 + 4090 / 910B，用户自行执行 `bash scripts/download_flashtalk.sh` 后启用
  - 即"无需手动下载 37GB 权重即可跑通基础 demo"——FlashTalk 仍是项目核心高质量方案，但不再是首次体验的硬门槛
- **Agent 化**：通过对接 OpenClaw 提供持续记忆和工具调用

### 1.2 宣传节奏（与里程碑对齐）

| 时间 | 里程碑 | 宣传主题 | 渠道 |
|------|--------|---------|------|
| Week 1 | M1 一键部署 | 准备期，不发布 | 内部种子用户邀请 |
| Week 2 | M2 个性化配置 | "一键部署 + 角色/音色/形象个性化" | HF / X / V2EX / 知乎 / B 站 |
| Week 3 | M3 差异化能力 | "可打断 + 音色克隆 + 性格化对话" | 同上 + 微信社群 / Reddit r/LocalLLaMA |
| Week 4 | M4 多硬件验证 | "从 3090 到 910B 同框架" + 完整 demo | Hacker News / Product Hunt / 中英博客 |

### 1.3 团队分工

采用**功能纵向切分**，每人负责一条端到端能力线：

| 角色 | 主线 | 协作点 |
|------|------|--------|
| 工程 1（Infra） | 部署 / 配置 / 硬件 / Benchmark | 与工程 2 对接模型 profile，与工程 3 对接配置 API |
| 工程 2（Model & Agent） | 模型适配 / OmniRT 客户端 / OpenClaw / 打断 | 与工程 3 对接 persona / voice profile API |
| 工程 3（Product & UX） | 前端 / 角色管理 / 音色 / Avatar 上传 | 与工程 1 / 2 对接 API |
| 宣传/文档 | README / demo 视频 / 博客 / 社区运营 | 与三位工程师同步交付物素材 |

---

## 2. 4 周里程碑总览

```
Week 1 (5/1-5/7)     M1: 一键部署可用            [内部验证, 不发布]
Week 2 (5/8-5/14)    M2: 个性化配置 + OpenClaw    [对外第一轮发布]
Week 3 (5/15-5/21)   M3: 差异化能力              [对外第二轮发布]
Week 4 (5/22-5/30)   M4: 多硬件 + 完整 demo       [对外第三轮 + Hacker News]
```

---

## 3. 每周 Checklist

每个 checklist 项采用 `任务 → 交付物 → 验收方式` 三段式。完成判定标准：交付物可执行 / 可演示 / 可链接。

### Week 1（5/1 - 5/7）M1 一键部署

#### 工程 1（Infra）

- [ ] **install.sh 一键脚本（Linux/macOS 主入口）**
  - 设计：install.sh 是 Linux/macOS 顶层入口，负责硬件探测 + 安装路径选择，本身不重复造轮子。Windows 单独走 install_windows 路径（见 Week 4），分文件维护
    1. 检测硬件：CUDA / Ascend / CPU + 显存大小
    2. 让用户选择安装方式：`native`（pip 安装）或 `docker`（拉预构建镜像）
    3. Docker 路径：根据硬件自动 `docker pull` 对应镜像并启动 compose
    4. Native 路径：创建 venv、按硬件安装 PyTorch / torch_npu
    5. **模型权重分层下载**：
       - 默认下载轻量模型（Wav2Lip / MuseTalk，数百 MB），保证首次体验快
       - 检测到 4090 / 910B 时**询问**用户是否同时下载 FlashTalk 14B（37GB），不强制
       - 提供独立脚本 `scripts/download_flashtalk.sh` 供后续升级到高质量路径
  - 交付：`scripts/install.sh` + `scripts/install_native.sh` + `scripts/install_docker.sh` + `scripts/download_flashtalk.sh`
  - 验收：
    - 在干净的 Ubuntu 22.04 + 4090 / 3090 / CPU 三种环境下，两种安装方式都能跑通 `bash install.sh && curl localhost:8000/health`
    - 默认轻量路径下载量 < 1GB，可在 5 分钟内完成首次启动
    - 用户后续可独立执行 download_flashtalk.sh 升级到高质量路径，无需重装
- [ ] **Docker 镜像矩阵（与 install.sh 配合）**
  - 交付：`docker/Dockerfile.unified-cuda`、`Dockerfile.unified-ascend`、`Dockerfile.unified-cpu` 推送至 ghcr.io
  - 镜像 tag 规范：`opentalking/unified:cuda-v0.1.0`、`unified:ascend-v0.1.0`、`unified:cpu-v0.1.0`
  - 验收：`docker run` 三个镜像均能启动 unified 服务并响应 health；install.sh docker 路径能正确选择
- [ ] **硬件 profile 配置框架**
  - 交付：`configs/profiles/{cuda-3090,cuda-4090,ascend-910b,cpu-demo}.yaml`，启动时通过 `OPENTALKING_HARDWARE_PROFILE` 选择，未指定时由 install.sh 写入默认值
  - 验收：4 个 profile 在 README 文档化，启动时打印当前 profile 与降级原因

#### 工程 2（Model & Agent）

- [ ] **FlashTalk 现状兼容性保护**（前置任务，必须先做）
  - 设计：当前 FlashTalk local/remote 模式是项目核心已用功能，新模型接入不能破坏
  - 交付：
    - 抽象 ModelAdapter 注册表，FlashTalk 作为现有适配器迁入新接口而非重写
    - 保留 `OPENTALKING_FLASHTALK_MODE=local|remote|off` 配置项向后兼容
    - 在 CI 加 FlashTalk 端到端冒烟测试（即使无 GPU 也能跑配置/启动检查）
  - 验收：现有 FlashTalk 用户升级到本月版本，无需改配置即可继续运行
- [ ] **Wav2Lip 适配器实化**（移除占位）
  - 交付：[src/opentalking/models/wav2lip/](https://github.com/datascale-ai/opentalking/blob/main/src/opentalking/models/wav2lip/) 完整实现 ModelAdapter 协议，支持单图 + 音频生成
  - 验收：CLI `generate_video` 用 wav2lip 模式跑通示例视频
- [ ] **MuseTalk 1.5 适配器**
  - 交付：[src/opentalking/models/musetalk/](https://github.com/datascale-ai/opentalking/blob/main/src/opentalking/models/musetalk/) 接入 MuseTalk 1.5 权重，支持流式推理
  - 验收：unified 服务下创建会话使用 musetalk 模型，前端能播放视频
- [ ] **模型选择策略层**
  - 交付：根据硬件 profile 自动选择默认模型（3090 → MuseTalk / Wav2Lip；4090 → MuseTalk 优先，FlashTalk 可选；910B → FlashTalk）
  - 验收：不同 profile 启动时打印 "Using model: xxx (reason: hardware profile cuda-3090)"
- [ ] **OmniRT service client 骨架**
  - 交付：`src/opentalking/inference/omnirt_client.py`，支持配置 endpoint + 调用 `audio2video` 任务面（即使 OmniRT 暂不可用也保留 fallback）
  - 验收：单元测试覆盖请求映射与错误处理

#### 工程 3（Product & UX）

- [ ] **前端 UI / IA 设计（前置任务，5/1-5/3 完成）**
  - 设计内容：
    1. **信息架构 (IA)**：站点导航树（首页 / 会话 / 角色管理 / 音色管理 / 系统信息 / 文档）
    2. **关键页面 wireframe**：
       - 主对话页（视频区 + 字幕区 + 输入区 + 当前角色卡片 + 打断按钮）
       - 角色管理页（列表 + 详情：avatar / voice / persona / skill）
       - 音色管理页（preset 列表 + 上传克隆 + 试听）
       - 系统信息页（硬件 profile + 模型 + 延迟数据）
    3. **组件库选型**：基于现有 React + Tailwind，引入 shadcn/ui 或 Radix UI 作为基础组件
    4. **设计 review**：5/3 团队 review 一次，确认方向后开发
  - 交付：[docs/design/wireframes.md](https://github.com/datascale-ai/opentalking/blob/main/docs/design/wireframes.md) + Figma / Excalidraw 链接（可选）
  - 验收：3 位工程师 + 1 位宣传都能看懂页面流程
- [ ] **角色配置 UI 骨架**（设计 review 通过后开始）
  - 交付：[apps/web/src/pages/PersonaConfig.tsx](https://github.com/datascale-ai/opentalking/blob/main/apps/web/src/pages/PersonaConfig.tsx)，包含角色列表、新建、编辑、删除四个基础页面
  - 验收：前端访问 `/personas` 可 CRUD 操作（后端 API mock 即可）
- [ ] **默认音色库（preset voices）**
  - 交付：6-12 个 preset voice（覆盖中文男女声 / 英文男女声 / 活泼 / 沉稳）配置文件 + 试听样音
  - 验收：前端音色选择器能列出、试听、绑定到角色
- [ ] **新 README + 项目首页**
  - 交付：README 按调研文档建议重写（用户价值优先），新增项目首页截图
  - 验收：README 在 GitHub 渲染正常，包含 30 秒 demo gif

#### 宣传/文档

- [ ] **demo 视频脚本（30 秒 + 1 分钟两个版本）**
- [ ] **博客 draft 1 篇**：项目介绍 + 设计动机
- [ ] **种子用户清单**：10-20 个潜在 early adopter（开源开发者社区）
- [ ] **宣传素材库初始化**：logo、配色、demo 截图、宣传语

#### Week 1 验收会议（5/7）

- 每人 demo 自己的交付物
- 跑一次端到端：`install.sh → 启动 → 创建会话 → 选择音色 → 说话 → 播放视频`
- 不通过则识别风险，决定 Week 2 是否调整宣传节奏

---

### Week 2（5/8 - 5/14）M2 个性化配置 + OpenClaw

#### 工程 1（Infra）

- [ ] **多硬件 profile 自动切换**
  - 交付：启动时检测硬件能力 → 自动选择最佳 profile，可通过环境变量覆盖
  - 验收：3090 / 4090 / Ascend 910B / CPU 启动均自动选择正确 profile
- [ ] **配置可视化端点**
  - 交付：`GET /config` API 返回当前 profile、模型、TTS 后端、硬件信息
  - 验收：前端"系统信息"页能展示当前配置

#### 工程 2（Model & Agent）

- [ ] **Agent / 记忆系统对接（主路径 OpenClaw + 2 个候选）**
  - 主路径：**OpenClaw adapter**
    - 交付：[src/opentalking/agents/openclaw/](https://github.com/datascale-ai/opentalking/blob/main/src/opentalking/agents/openclaw/) adapter，把会话输入透传给 OpenClaw，接收响应文本和结构化字段
    - 验收：会话能调用 OpenClaw 完成多轮对话，记忆状态由 OpenClaw 维护
  - 候选 1：**[Mem0](https://github.com/mem0ai/mem0)**（轻量记忆层）
    - 特点：开源、API 友好、支持向量化用户偏好和事实记忆，1-2 行代码集成
    - 适合场景：陪伴型场景的事实/偏好记忆（"用户喜欢的电影"、"用户工作"）
    - 集成成本：低（约 0.5 人天）
    - 用途：作为 OpenClaw 阻塞时的 fallback，或作为陪伴型场景"个性记忆"补充层
  - 候选 2：**[Letta（前 MemGPT）](https://github.com/letta-ai/letta)**（长记忆 + 自管理上下文）
    - 特点：支持 hierarchical memory、self-editing memory、长期对话状态机
    - 适合场景：陪伴型场景需要"几十次对话仍记得用户细节"的长期记忆
    - 集成成本：中（约 1-2 人天，需部署 letta server）
    - 用途：高质量私有化路线下的长期记忆方案
  - 抽象设计：定义 `MemoryProvider` 接口，OpenClaw / Mem0 / Letta / null 都可作为实现注入；前端通过配置切换
  - 验收：至少 OpenClaw 主路径可用；Mem0 / Letta 至少完成接口验证（可不上线）
- [ ] **Persona package 数据结构**
  - 交付：`src/opentalking/persona/` 模块，定义 persona = avatar + voice + system_prompt + skill_set
  - 验收：可从 yaml 加载 persona，可通过 API CRUD
- [ ] **全链路打断初版**
  - 交付：扩展现有 `_interrupt` 标志到 LLM / TTS / 模型推理 / WebRTC frame queue
  - 验收：用户中途打断 → 1 秒内停止说话并切到 idle

#### 工程 3（Product & UX）

- [ ] **多音色切换 UI**
  - 交付：角色配置页支持选择音色、试听、保存为默认
  - 验收：切换音色后下次说话使用新音色
- [ ] **Avatar 上传图片生成（基础版）**
  - 交付：上传单张图片 → 后台异步生成 avatar bundle（用于 wav2lip / musetalk）
  - 验收：用户上传图片 30 秒内完成生成，能创建会话使用该 avatar
- [ ] **性格配置 UI**
  - 交付：性格 = 预设性格模板（温柔 / 活泼 / 严肃 / 幽默）+ 自定义 system prompt
  - 验收：选择性格后对话风格符合预期

#### 宣传/文档

- [ ] **第一轮发布素材**：30 秒 demo 视频、Twitter 长帖、知乎文章、V2EX 帖、B 站短视频
- [ ] **HF 模型卡 / Space**：在 HuggingFace Space 部署在线 demo
- [ ] **第一轮发布执行**（5/13 或 5/14）
  - 渠道：X、知乎、V2EX、B 站、微信开源社群
  - 目标：第一周新增 200-400 star
- [ ] **博客 1 发布**

#### Week 2 验收（5/14）

- 端到端验证：`安装 → 创建角色（上传图片+选择音色+性格）→ 多轮对话（OpenClaw 记忆）→ 中途打断`
- Star 数据采集
- 复盘第一轮发布反馈，调整 Week 3 重点

---

### Week 3（5/15 - 5/21）M3 差异化能力

#### 工程 1（Infra）

- [ ] **Benchmark CI**
  - 交付：`.github/workflows/benchmark.yml`，每次 PR 跑端到端延迟测试（TTFA / TTFV / E2E）
  - 验收：CI 报告能展示历史趋势
- [ ] **延迟数据看板**
  - 交付：前端"性能"页展示当前会话的 TTFA / TTFV / FPS / 队列深度
  - 验收：用户能直观看到延迟数据

#### 工程 2（Model & Agent）

- [ ] **音色克隆接入（via OmniRT）**
  - 交付：用户上传 30 秒参考音频 → 调用 OmniRT `voice_clone` task → 生成 voice_id
  - 验收：克隆音色可用于 TTS 合成（如 OmniRT 暂未提供，本仓直连 CosyVoice 2.0 作为过渡）
- [ ] **全链路打断稳定**
  - 交付：打断响应 < 500ms，无视频卡顿，无音频残留
  - 验收：100 次打断测试 0 失败
- [ ] **打断的语音输入触发**
  - 交付：浏览器麦克风 + VAD 检测用户开口 → 自动打断
  - 验收：用户开口说话 1 秒内数字人停止

#### 工程 3（Product & UX）

- [ ] **数字人 Skill 配置**
  - 交付：预设技能模板（陪聊、口语练习、知识问答、情绪树洞、角色扮演 5 个）
  - 验收：用户选择 skill 后角色行为符合模板设定
- [ ] **音色克隆 UI**
  - 交付：上传参考音频 + consent 勾选 + 试听克隆结果 + 命名保存
  - 验收：从上传到可用 < 30 秒
- [ ] **会话历史 UI**
  - 交付：展示对话历史、字幕回看、会话回放
  - 验收：刷新后历史保留

#### 宣传/文档

- [ ] **第二轮发布素材**：1 分钟 demo（包含打断 + 克隆音色）+ 技术博客 2
- [ ] **HF Space 更新到 M3 版本**
- [ ] **第二轮发布执行**（5/20 或 5/21）
  - 渠道：第一轮全部 + Reddit r/LocalLLaMA + Reddit r/MachineLearning
  - 目标：累计达到 700-1000 star

#### Week 3 验收（5/21）

- 端到端验证：克隆音色 + 打断 + skill 切换
- Star 数据评估，决定 Week 4 是否需要加码

---

### Week 4（5/22 - 5/30）M4 多硬件验证 + 完整 demo

#### 工程 1（Infra）

- [ ] **完整 Benchmark 报告**
  - 交付：[docs/benchmark.md](https://github.com/datascale-ai/opentalking/blob/main/docs/benchmark.md) 包含 4090 / 3090 / 910B 三套硬件的：
    - TTFA / TTFV / E2E 延迟
    - 稳态 FPS
    - 显存/NPU 占用
    - 长时稳定性（30 分钟连续会话 drop frame 率）
  - 验收：数据可重复，附原始日志
- [ ] **部署文档矩阵**
  - 交付：`docs/deployment/` 下分目录覆盖 Docker / K8s / 单机 / 私有化四种场景
  - 验收：文档可独立按步骤跑通
- [ ] **install.sh 鲁棒性强化**
  - 交付：处理网络波动、镜像源切换、版本兼容
  - 验收：在 5 台不同环境上 100% 成功
- [ ] **跨平台基础防御**（最小必要工作，不做完整 Windows 支持）
  - `.gitattributes` 强制所有 `*.sh` 用 LF 换行符，避免 Windows checkout 后无法执行
  - README 明确说明"本月仅支持 Linux / macOS，Windows 支持在 6 月计划中"
  - 验收：Windows 用户 git clone 后 *.sh 文件换行符正确

#### 工程 2（Model & Agent）

- [ ] **稳定性修复 sprint**
  - 交付：所有 Week 1-3 issue 关单 ≥ 90%
  - 验收：开放 issue 数 < 10
- [ ] **端到端延迟优化**
  - 目标：4090 端到端首响 < 2s，TTFA < 500ms
  - 验收：benchmark CI 显示达标

#### 工程 3（Product & UX）

- [ ] **完整产品 demo 录制**
  - 交付：3-5 分钟完整 demo 视频，覆盖所有核心能力（部署 / 配置 / 对话 / 打断 / 克隆 / skill）
  - 验收：视频可直接投递 Hacker News / Product Hunt
- [ ] **案例展示页**
  - 交付：项目主页新增"用户案例"区，展示 5 个典型场景配置
  - 验收：每个案例有截图 + 配置文件 + 视频片段

#### 宣传/文档

- [ ] **Hacker News 投递**（5/27 或 5/28，工作日美东时间早上）
- [ ] **Product Hunt 准备**（备选）
- [ ] **中英文长博客**：技术回顾 + 路线图展望
- [ ] **第三轮发布**（5/28）
  - 目标：累计达成 1000-2000 star
- [ ] **5/30 复盘报告**
  - 数据：star 增长曲线、issue 数、PR 数、社区活跃度
  - 经验：哪些渠道效果好，下月重点

#### Week 4 验收（5/30）

- Star 数 ≥ 1000（必达）/ ≥ 2000（挑战）
- 完整 demo 视频已发布
- Benchmark 数据已发布
- 月度复盘报告已写

---

## 4. 宣传策划详细方案

### 4.1 渠道矩阵

| 渠道 | 受众 | 投递频次 | 内容形式 |
|------|------|---------|---------|
| GitHub README | 开发者 | 每个里程碑更新 | 文字 + gif + 截图 |
| HuggingFace Space | AI 开发者 | 每个里程碑更新 | 在线 demo |
| X / Twitter | 全球 AI 圈 | 每个里程碑发 1 条主帖 + 日常 | 短视频 + 长帖 |
| 知乎 | 中文技术圈 | 每个里程碑 1 篇 | 长文 + demo |
| V2EX | 中文开发者 | 每个里程碑 1 帖 | 简洁链接帖 |
| B 站 | 中文视频用户 | 每个里程碑 1 视频 | 横屏短视频 |
| 微信开源社群 | 中文社区 | 每个里程碑同步 | 卡片 + 链接 |
| Reddit r/LocalLLaMA | 海外本地部署用户 | M3 / M4 各 1 帖 | 文字 + 视频链接 |
| Hacker News | 海外开发者 | M4 投递 1 次 | 标题 + 链接 |
| Product Hunt | 海外产品用户 | M4 备选 | 完整产品页 |

### 4.2 关键 Hook（吸 Star 的钩子）

按重要性排序，每个 Hook 对应一个明确的视觉/文字记忆点：

1. **"3 行命令跑起本地数字人"** — 一键部署的极简体验（M1）
2. **"上传一张照片 + 30 秒声音 = 你的专属陪伴 AI"** — 个性化（M2/M3）
3. **"可打断的对话，像和真人聊天"** — 实时性差异化（M3）
4. **"从 3090 到 910B，同一个框架"** — 硬件兼容（M4）
5. **"基于 OpenClaw 的持续记忆"** — Agent 化（M2-M4）

### 4.3 内容素材清单

| 素材类型 | 数量 | 谁负责 | 截止 |
|---------|------|--------|------|
| 30 秒 demo 视频 | 1 | 工程 3 + 宣传 | Week 1 末 |
| 1 分钟 demo 视频 | 1 | 工程 3 + 宣传 | Week 2 末 |
| 3-5 分钟完整 demo | 1 | 工程 3 + 宣传 | Week 4 中 |
| README gif（核心场景） | 3-5 | 工程 3 | Week 1 末 |
| 技术博客 | 2-3 | 宣传 + 工程 2 | Week 2/3/4 |
| HF Space 在线 demo | 1 | 工程 1 | Week 2 |
| 项目首页截图 | 5-10 | 工程 3 | Week 1 末 |

### 4.4 数据追踪

- 每日记录 Star / Fork / Issue / PR 数
- 每周分析增长来源（HF / Reddit / X / 知乎 / 直接访问）
- M4 周末输出月度复盘

---

## 5. 开源整改 / 易用性优化

这部分作为贯穿全月的横向工作，按 Week 排期：

### Week 1
- [ ] LICENSE 文件检查（Apache 2.0 已在）
- [ ] CONTRIBUTING.md 完善
- [ ] CODE_OF_CONDUCT.md
- [ ] Issue / PR 模板
- [ ] GitHub Actions CI 基础（lint / typecheck / unit test）

### Week 2
- [ ] CHANGELOG.md 启用并随发布更新
- [ ] 中英文 README 同步
- [ ] 错误信息友好化（启动失败时给出明确提示）
- [ ] FAQ 文档（覆盖前 20 个常见问题）

### Week 3
- [ ] 版本化发布（v0.1.0）+ GitHub Release
- [ ] PyPI 包发布（`pip install opentalking`）
- [ ] Docker 镜像 tag 规范
- [ ] 配置项文档自动生成

### Week 4
- [ ] 完整 API 参考文档（OpenAPI 自动生成）
- [ ] 多语言文档站点（VitePress / Docusaurus）
- [ ] 安全合规文档（隐私、consent、watermark 说明）
- [ ] 贡献者名单（all-contributors）

---

## 6. 风险识别与降级策略

| 风险 | 概率 | 影响 | 降级 |
|------|------|------|------|
| OpenClaw 集成阻塞 | 中 | 高 | Week 2 改为本仓轻量 persona + session memory，下月再迁 |
| 音色克隆 OmniRT 端未就绪 | 高 | 中 | 直连 CosyVoice 2.0 作为过渡，本仓加 voice service abstraction |
| MuseTalk 1.5 接入复杂度高 | 中 | 中 | 退回 MuseTalk 1.0；保留接口，下月再升级 |
| Avatar 上传生成质量差 | 高 | 中 | 先支持"参考帧裁剪 + idle 动画"轻量版本，不做高质量重建 |
| Star 增长不达 1000 | 中 | 高 | Week 3 中评估，必要时增加 Hacker News 提前到 Week 3 末，或加大社群推广 |
| 4090 跑不动 FlashTalk | 高 | 低 | 文档明确"4090 跑轻量模型，FlashTalk 推荐 910B/H100"，不做硬性承诺 |
| 团队 1 人临时缺席 | 中 | 中 | 工程 1/2 可互相顶替部署/模型；工程 3 前端单点风险最高，需提前 pair |

---

## 7. Benchmark 体系

本月需建立可持续的性能数据采集口径，作为后续路线图的决策依据。

### 7.1 核心指标

| 指标 | 含义 | 目标值（4090） | 目标值（910B） |
|------|------|---------------|----------------|
| TTFA (Time To First Audio) | 用户输入完成 → 第一段 PCM | < 500ms | < 400ms |
| TTFV (Time To First Video) | 第一段 PCM → 第一帧视频 | < 1s | < 1s |
| E2E 首响 | 用户输入 → 数字人开始说话 | < 2s | < 1.5s |
| 稳态 FPS | 持续会话帧率 | ≥ 25 | ≥ 25 |
| 打断响应 | 用户打断 → 数字人停止 | < 500ms | < 500ms |
| AV drift | 音视频同步偏差 | < 80ms | < 80ms |
| 长时稳定性 | 30 分钟连续会话 drop frame 率 | < 1% | < 0.5% |

### 7.2 测试场景

1. **轻量模型 benchmark**：3090 + Wav2Lip / MuseTalk
2. **高质量 benchmark**：4090 + FlashTalk 量化版（如可行） / 910B + FlashTalk
3. **打断响应 benchmark**：100 次打断的延迟分布
4. **多并发 benchmark**：单机支持的最大并发会话数（M4 选做）

### 7.3 工具

- 本仓内：[scripts/benchmark/](https://github.com/datascale-ai/opentalking/blob/main/scripts/benchmark/)（待新建）+ Benchmark CI
- 外部：引用 OmniRT 的 RunReport 数据

---

## 8. 5/30 验收标准

月底验收会议必须满足以下硬性条件：

- [ ] Star 数 ≥ 1000（必达），≥ 2000（挑战）
- [ ] M1-M4 四个里程碑全部交付
- [ ] 完整 3-5 分钟 demo 视频已发布
- [ ] Benchmark 报告（4090 + 910B）已发布
- [ ] HF Space 在线 demo 可访问
- [ ] PyPI 包可安装（`pip install opentalking`）
- [ ] 一键部署脚本在 3 种环境验证通过
- [ ] 月度复盘报告已写

---

## 9. OmniRT 协同推进计划（外部仓配套路线图）

[OmniRT](https://github.com/datascale-ai/omnirt) 是面向数字人的多模态生成推理统一运行时，把音频、图像、视频、TTS / Avatar 模型稳定服务化（类比 vLLM 在 LLM 领域的角色，但面向多模态生成）。本月 OpenTalking 的演进高度依赖 OmniRT 的并行推进——以下不是 OpenTalking 仓的工作，但需要与 OmniRT 团队对齐节奏，避免 OpenTalking 做完发现下游服务没就绪。

### 9.1 OmniRT 本月需交付的能力（按 OpenTalking 里程碑倒推）

| OmniRT 能力 | OpenTalking 依赖里程碑 | 优先级 | 状态/动作 |
|------------|----------------------|-------|---------|
| `audio2video` 任务面（FlashTalk） | M1 (Week 1) | P0 | 已就绪（`soulx-flashtalk-14b` registry 已存在）→ 仅需文档化 endpoint 协议 |
| 服务健康检查 / RunReport 字段稳定 | M1 (Week 1) | P0 | 已有 Prometheus / OTel 基础 → 需冻结 RunReport schema |
| **`streaming_tts` 任务面**（首包 < 500ms） | M2 (Week 2) | P0 | **需新增**：候选后端 CosyVoice 2.0 / Fish Audio S2 / VibeVoice-Realtime |
| **`voice_clone` 任务面**（30 秒参考音频 → voice_id） | M3 (Week 3) | P0 | **需新增**：候选后端 CosyVoice / GPT-SoVITS / F5-TTS |
| **`streaming_audio2video`**（chunk 流式输出，FlashTalk resident worker） | M3 (Week 3) | P1 | **需新增**：当前 `audio2video` 主要返回 MP4 artifact，需扩展 chunk streaming |
| **轻量 avatar 模型注册**（MuseTalk 1.5 / Wav2Lip） | M2 (Week 2) | P1 | **需新增**：当前只有 FlashTalk，需把消费级模型纳入 registry |
| `voice_design` 任务面（自然语言描述音色） | M4 (Week 4) | P2 | 选做：可作为 ElevenLabs provider 封装先上线 |
| 4090 / 3090 backend profile | M4 (Week 4) | P1 | **需新增**：当前 backend 主要是 Ascend，需 CUDA consumer profile |

### 9.2 协同节奏

```
Week 1 (5/1-5/7)
  OmniRT: 冻结 audio2video / RunReport schema，文档化 client 协议
  OpenTalking: 工程 2 实现 omnirt_client 骨架，对接现有 audio2video

Week 2 (5/8-5/14)
  OmniRT: 上线 streaming_tts（CosyVoice 2.0 P0），完成轻量 avatar 注册（MuseTalk 1.5）
  OpenTalking: M2 接入 streaming_tts，验证首包延迟

Week 3 (5/15-5/21)
  OmniRT: 上线 voice_clone（CosyVoice 2.0），扩展 streaming_audio2video chunk API
  OpenTalking: M3 接入音色克隆，FlashTalk 切到 chunk 模式

Week 4 (5/22-5/30)
  OmniRT: CUDA backend profile（3090 / 4090），benchmark 数据补全
  OpenTalking: M4 端到端 benchmark 报告引用 OmniRT 数据
```

### 9.3 OmniRT 的"分担"职责（避免 OpenTalking 重复造轮子）

OpenTalking **不做**以下事情，全部交给 OmniRT 推进：

- ❌ 不在本仓维护 CosyVoice / GPT-SoVITS / F5-TTS / VibeVoice 的 Python adapter
- ❌ 不在本仓做 voice clone 模型推理（包括上传音频的特征提取）
- ❌ 不在本仓维护 FlashTalk resident worker（gRPC、queue、batching）
- ❌ 不在本仓写各模型的 benchmark 框架（只引用 OmniRT 的 RunReport）
- ❌ 不在本仓维护 backend 抽象（CUDA / Ascend / NPU 切换）

OpenTalking **只做**以下事情：

- ✅ 维护 OmniRT service client（HTTP/gRPC）
- ✅ 把 OpenTalking 的会话/avatar/persona 概念映射到 OmniRT 请求
- ✅ 消费 OmniRT 的 RunReport / health / queue depth 并展示到前端
- ✅ 提供 fallback：OmniRT 不可用时回退到本仓 demo renderer 或老 FlashTalk WS
- ✅ 维护 voice_profile 元数据（id、provider、consent、绑定的 persona）

### 9.4 风险点

- **streaming_tts 进度滞后**：M2 上线压力最大，OmniRT 端需明确 owner 和 5/12 之前的可用性承诺
- **streaming_audio2video chunk API**：当前未实现，是 M3 实时性差异化的关键。如果 5/18 前未就绪，OpenTalking 用旧 FlashTalk WS 兜底
- **协议变更频率**：OmniRT 仍在迭代，建议本月只用 OpenTalking 真正依赖的字段，避免被 schema 变更打断

### 9.5 跨仓沟通机制

- 每周一同步会（30 分钟）：双方负责人对齐 milestone 进度
- 共享 GitHub Project board（label：`opentalking-blocker`、`omnirt-blocker`）
- 关键变更走 PR + cross-repo review

---

## 10. 与调研文档的关系

本月计划聚焦"实时交互体验 + 个性化 + 多硬件"，与 [realtime-digital-human-research.md](../design/realtime-digital-human-research.md) 中能力域 A/B/C/D/F/G/H 对齐。本月不覆盖的范围：

- **能力域 E（高质量私有化部署进阶）**：本月只做 910B benchmark 引用，深度调度/多并发推迟到 6 月
- **能力域 I（平台化和安全合规）**：本月仅做最小合规（consent 勾选 + watermark 文档），完整体系 6-7 月
- **OmniRT 内部建设**：始终是外部仓职责，本月只做 service client

下月（6 月）起把重点切换到：

1. 多并发 session scheduler
2. 平台化指标（Prometheus / OTel）
3. 多人对话 POC
4. 移动端 / 浏览器端轻量 fallback（TalkingHead / 3D avatar）
5. **Windows 支持**：独立 `install_windows.ps1`、Docker Desktop + WSL2 + NVIDIA Container Toolkit 完整流程、windows.md 部署指南
6. **新场景扩展**：AI 电商带货、个人数字分身（详见下文 § 10.1 / § 10.2）

---

### 10.1 新场景兼容性分析（6 月规划起点）

OpenTalking 的中长期目标不止"陪伴型数字人"，还需要支持以下两个高价值场景。本节先做架构兼容性判断，5 月不做大改动，6 月起规划落地。

#### 场景 A：AI 电商带货

**典型需求**：

- 长时间（3-6 小时）连续直播，稳定不掉线
- 推流到淘宝直播 / 抖音 / 视频号 / B 站等平台（非 WebRTC P2P）
- 1:N 广播模型（一个 AI 主播 → 数千观众）
- 观众弹幕作为输入流，主播实时回应
- 产品知识库（RAG）+ 价格 / 库存 / 优惠券实时数据
- 强情绪化语音（"宝宝们！"、"上链接！"）
- 屏幕叠加产品图 / 视频片段
- 直播控场：开播流程、商品讲解节奏、催单话术

**当前架构对齐**：

- ✅ Persona + Skill：可定义"带货主播 skill"
- ✅ OpenClaw / RAG：产品知识库委托外部 Agent
- ✅ 多硬件：910B 长时稳定 / 4090 中小直播
- ✅ 音色克隆：可克隆达人音色

**关键缺口**：

| 缺口 | 影响 | 6 月动作 |
|------|------|---------|
| 缺 RTMP / FLV / HLS 推流 | 无法推到直播平台 | 把 `rtc/` 抽象为 `transport/`，新增 `RTMPTransport` |
| 1:N 广播架构 | 当前 1:1 session 模型 | 新增 `BroadcastSession` 类型，支持弹幕输入流 |
| 弹幕/评论输入通道 | 当前只有文本 / 麦克风 | 抽象 `InputSource` 接口，新增 DanmuSource、CommentSource |
| 屏幕叠加（产品展示） | 当前是单视频流 | 前端 + 推流端引入合成层（OBS-like） |
| 长时稳定性 | 当前未验证 6 小时不间断 | benchmark 增加"6 小时连续会话"测试 |

#### 场景 B：个人数字分身

**典型需求**：

- 高保真克隆（形象 + 音色 + 性格 + 专业知识）
- 长期记忆（数月前的对话仍记得）
- 多技能模式：工作助理 / 社交陪伴 / 内容创作
- 离线视频生产（短视频、教程、播客）
- 多端部署（Web / 移动 / 桌面 client）
- 数据隐私 / 用户拥有 avatar 数据
- 可选商业化（卖给粉丝订阅）

**当前架构对齐**：

- ✅ Avatar 上传生成（M2）
- ✅ 音色克隆（M3）
- ✅ Persona package
- ✅ OpenClaw / Letta 长期记忆
- ✅ Skill 切换

**关键缺口**：

| 缺口 | 影响 | 6 月动作 |
|------|------|---------|
| 离线视频生成 pipeline | 短视频内容生产无法支持 | 独立 `offline_worker`，支持脚本 → 多段视频 → 配乐拼接 |
| 移动端 client | 仅 Web 控制台 | 6 月做 H5 适配，7 月做原生 SDK |
| 用户数据所有权 | 当前 avatar 数据归服务端 | 增加导出 / 加密 / 联邦化方案 |
| 内容质量打磨 | 短视频对面部细节要求更高 | 引入 SoulX-FlashHead / GeneFace++ 等更高质量模型 |
| 多平台一致性 | persona 在 Web / 移动 / 接入第三方时表现一致 | 标准化 persona export 协议 |

### 10.2 6 月架构演进建议

为支持上述场景，6 月架构演进的核心是**抽象 3 个边界**，避免每个新场景都要重写：

#### 1. Transport 层抽象

```
当前：rtc/aiortc_adapter.py  (硬绑定 WebRTC)

6 月：transport/
        base.py            (Transport 接口)
        webrtc.py          (现有实现)
        rtmp.py            (新增，电商带货)
        file_writer.py     (新增，离线视频)
        recorder.py        (新增，会话录制)
```

#### 2. Session 类型抽象

```
当前：单一 Session 概念，假设 1:1

6 月：base_session.py
        ChatSession      (1:1，陪伴 / 数字分身)
        BroadcastSession (1:N，电商带货 / 直播)
        OfflineSession   (无观众，内容生产)
```

#### 3. Input Source 抽象

```
当前：HTTP /speak 文本 + 麦克风

6 月：input/
        text_source.py     (现有)
        mic_source.py      (现有)
        danmu_source.py    (新增，弹幕)
        comment_source.py  (新增，评论)
        scheduled_source.py(新增，定时脚本)
```

### 10.3 6 月里程碑建议

基于上述分析，6 月可分两个并行轨道：

**轨道 A：平台化（5 月计划延续）**
- 多并发 session scheduler
- Prometheus / OTel
- Windows 支持
- Kubernetes manifests

**轨道 B：新场景架构预备（为 AI 带货 / 数字分身铺路）**
- Transport / Session / Input Source 三层抽象重构
- RTMP 推流原型（最小可用）
- 离线 video generation pipeline 原型
- 6 小时长时稳定性 benchmark
- 移动端 H5 适配调研

具体的 6 月计划文档将在 5/30 月度复盘后单独制定。本月不做新场景的代码改动，仅在 5 月计划执行中**保持架构开放性**——任何 PR 不要做"硬绑定 WebRTC / 1:1 会话"的设计决策。

### 10.4 给团队的具体建议（5 月执行时注意）

虽然本月不做新场景的架构改动，但执行 5 月计划时，请遵守以下原则避免 6 月重构成本：

- **不要在新代码里硬编码 "WebRTC"** —— 如果一定要写，留 TODO 标记
- **Persona / Session schema 评审时**，预留扩展字段（`session_mode`、`use_case`、`metadata`），即使本月只用一个值
- **OmniRT client 的请求映射**，按"任务面"组织而非"模型名"，未来加 `text2video_offline` 任务面时不冲突
- **音色 / Avatar 的元数据**，增加 `owner_id`、`consent`、`license` 字段（数字分身需要数据所有权）
- **避免假设"前端只有 Web 控制台"** —— API 设计保持 framework-agnostic，方便未来对接移动端 / 第三方
