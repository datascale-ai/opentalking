# 知识库文档上传提速规划

> 分支：`improve-knowledge-upload`
> 范围：第一阶段、第二阶段
> 状态：规划与实现对照记录（业务代码已在本分支落地基础版本；本文不包含后续未实现能力的虚假结论）。
> 目标：缩短知识库文档上传的用户等待时间，同时避免文档处理拖慢实时数字人会话。

本文记录本分支已落地的第一、二阶段实现、验收结果和剩余工作；后续仅继续补充文档与测试
说明，不在本文中把尚未实现的优化写成已完成结果。

截至 2026-09-04，本分支已进入实现验证阶段；代码、测试和基准脚本均可能继续迭代，以下
“已实现”以当前工作区为准，提交前需再次执行完整验收。

## 0. 针对“超过 10KB 卡很久”的直接回答

这次采用“异步解耦 + 根因降本”两条线同时处理，而不是只把函数改名为
`async`：

```text
上传请求：流式落盘 → 校验/hash → 写入最小文档记录 → 提交任务 → 立即返回 uploaded
后台 worker：抽取/OCR → 切分 chunks → 批量写 SQLite → 受控 LightRAG 索引 → ready/error
```

因此，10KB 以上文档不会再让 HTTP 请求一直等到 LightRAG 完成；实时会话也不会被
解析、SQLite 或索引工作占住 FastAPI 事件循环。当前已落地的“根因降本”包括：

- 所有 `KnowledgeStore` 阻塞操作统一进入有界线程池，避免事件循环阻塞；
- chunks 使用单事务 `executemany()` 批量写入，减少逐行 SQLite 往返；
- 同知识库索引任务串行、跨知识库使用有界并发，避免索引互相覆盖和资源失控；
- 使用 Redis `(kb_id, doc_id)` 幂等键，避免同一文档重复排队；
- API、文件池、文件池导入、创建知识库时上传/导入等入口均走 deferred 路径；staging
  文件在同文件系统上使用原子移动，跨文件系统才回退为单次流式复制并计算 hash。

需要明确：当前版本已经解决“用户等待很久”和“上传拖慢其他请求”，并已对重试/批量路径
避免重复抽取；但还没有完成全部的计算降本。首次 worker 仍会抽取文本，并调用现有 LightRAG 文档索引；
真实 provider 上的批量 embedding、LightRAG 上下文复用效果和独立 fast-index/enrichment
流水线仍需压测/扩展。也就是说，当前收益首先体现在
`upload_ack_latency`，而不是宣称 `index_ready_latency` 已经达到最终目标。

### 0.1 当前实现的实际时序

直接上传到知识库时，代码实际按以下顺序运行：

```text
POST /agent/knowledge-bases/{kb_id}/documents
  1. 路由按 1 MiB 分块接收 UploadFile，写入临时文件（仍受 20 MiB 限制）
  2. KnowledgeStore 在有界 executor 中校验扩展名、大小和 SHA256，检查重复
  3. 将 staging 文件原子移动（跨文件系统时单次流式复制）到知识库 documents 目录，并在 SQLite 创建 status=uploaded 的最小记录
  4. 路由向 Redis TASK_QUEUE 写入 knowledge_index（NX 幂等，携带 generation/content_hash）；无 Redis 时使用 FastAPI BackgroundTasks
  5. 返回 KnowledgeDocumentResponse(status=uploaded, chunk_count=0)

后台 knowledge_index worker
  6. 同一 kb_id 获取 asyncio.Lock；所有知识库共享有界 semaphore
  7. 对已有完整 chunks 的 enrichment 重试/批量任务直接复用 SQLite 文本；只有 uploaded 或显式重建才读取文件并抽取
  8. 在一个 SQLite 事务中批量写入 chunks，更新 status=indexing
  9. 本地 chunks 先更新为 ready_fast；随后调用 KnowledgeIndex/LightRAG，成功后更新 ready；增强失败则保留文件和 chunks，维持 ready_fast/enrichment 并由 worker 重试
```

文件池上传先执行步骤 1–3，写入 `knowledge_files(status=uploaded)`，随后由
`knowledge_prepare_file` worker 完成抽取和 `knowledge_file_chunks` 批量落库；从文件池导入
知识库时只复制已准备好的内容并提交 `knowledge_index`。创建知识库时传入的
`document_ids` 和 `files` 也走同样的 deferred 分支，因此不会因为 WebUI 的“先文件池、后建库”
流程重新落回同步 LightRAG。

这意味着“上传接口返回”与“文档可检索”之间必然存在一个可观察窗口。客户端应把
`uploaded/indexing` 显示为处理中，轮询列表或状态接口直到 `ready`，而不能把首响应直接当成
索引完成。

### 0.2 第一、二阶段完成后的用户收益判断

是的，完成第一、二阶段后，大部分上传体验会明显变好：

- 10KB、20KB、50KB 文本的 HTTP 首响应不再等待解析、embedding 或图谱抽取；
- 上传一个大文件时，健康检查、知识库列表和实时会话请求不会被同一事件循环同步代码拖住；
- 多文件上传可以连续提交，后台按受控并发处理，页面可显示每个文件的处理中/完成/失败状态；
- 失败文档保留原文件和元数据，worker 重启后可恢复，用户不必重新上传。

但“后台处理完成的绝对时间”不会仅因 `BackgroundTasks` 自动变短。要从根本上缩短
`index_ready_latency`，必须完成本文第 6 节列出的批量 embedding、LightRAG 上下文复用、
hash 缓存和 fast-index/enrichment 拆分，并用同模板 8/10/12/20/50KB 基准证明。否则本分支
只能承诺“先返回、并发不被拖慢”，不能承诺“LightRAG 本身已经快了同样的比例”。

## 1. 结论先行

第一、二阶段会改善大部分上传体验，但需要区分两个“速度”指标：

| 指标 | 第一阶段：移出事件循环 + 批量落库 | 第二阶段：索引异步化 + 状态机 | 能否改善 |
| --- | --- | --- | --- |
| 点击上传后 WebUI/API 是否卡住 | 明显改善 | 进一步改善 | 是，覆盖大多数体验问题 |
| 文档超过约 10KB 后 HTTP 长时间不返回 | 只能避免拖住其他请求，当前请求仍可能等待索引 | 上传确认与索引完成彻底分离 | 第二阶段才真正解决“卡住”感知 |
| 单个小型 `.txt/.md` 的文件接收速度 | 小幅改善 | 基本不变 | 主要受网络和磁盘影响 |
| 多文件上传总等待时间 | 中等改善 | 显著改善 | 是 |
| 上传接口返回首响应时间 | 小幅改善 | 显著改善 | 是 |
| PDF 文本解析耗时 | 不改变算法，仅不阻塞主循环 | 可移至后台，不再阻塞请求 | 用户感知显著改善 |
| 扫描 PDF OCR 耗时 | 不改变 OCR 本身 | 可后台执行，可并发/限流 | 是，但处理完成时间仍取决于 OCR |
| LightRAG embedding/索引的真实计算量 | 基本不变 | 批量 embedding 后才会下降 | 第一、二阶段本身不保证下降 |
| 多进程/多会话期间实时对话流畅度 | 明显改善 | 显著改善 | 是 |

因此：

1. 第一阶段解决“同步代码占用 FastAPI 事件循环”的结构性问题。
2. 第二阶段解决“上传请求同步等待 LightRAG”的主等待问题。
3. 如果只做到第一阶段，系统会更能并发，但单个上传仍可能等待索引完成。
4. 如果第二阶段只做后台任务、仍按文档逐个初始化 LightRAG，则用户等待会变短，但索引端到端耗时未必明显下降。
5. 真正的根本提速需要第二阶段同时设计批量索引/embedding、持久化索引实例或专用索引 worker；这部分属于第二阶段的实现目标，但应作为独立可验收项，不能被“接口立即返回”掩盖。

对于“超过 10KB 就卡很久”的现象，规划不能只写成 `asyncio.to_thread()`：如果只是把仍然包含 LightRAG 的整段 `_add_document_sync()` 放进线程池，HTTP 请求依旧会等待 LightRAG，最多只是事件循环不再被占用。本文将“用户不再等待”和“索引本身变快”拆成两个必须分别验收的结果：

- 第一阶段：上传处理不阻塞 FastAPI 事件循环，并减少本地落库成本；
- 第二阶段：HTTP 在文件和 chunks 安全落库后立即返回 `indexing`，同时通过批量 embedding、LightRAG 上下文复用以及延后非必要图谱处理，缩短真正的 `index_ready_latency`。

## 2. 当前实现基线

### 2.1 当前上传路径

知识库文档上传入口位于 `apps/api/routes/agent.py`：

```text
UploadFile 分块写临时文件
  → KnowledgeStore.add_document()
  → 校验扩展名/大小/重复内容
  → SHA256
  → 复制到知识库目录
  → _extract_text()
  → _split_chunks()
  → SQLite 写入文档和 chunks
  → LightRAG index_document()
  → 返回 KnowledgeDocumentResponse
```

文件池上传路径相同，只是落到 `_file_pool`，之后通过 `add_existing_document()` 复制到具体知识库。

### 2.2 已确认的瓶颈

1. `KnowledgeStore` 的异步外观没有真正异步化。

   `add_document()`、`add_file()`、`add_existing_document()`、`reindex_document()`、`query()` 等 async 方法直接调用对应的同步实现。当前上传请求会在事件循环线程内执行文件读写、解析、SQLite 和索引。

2. 上传请求同步等待 LightRAG。

   `_add_document_sync()` 在写完 SQLite 后直接调用 `_index_document_best_effort_sync()`。后者调用 `KnowledgeIndex.index_document()`，默认实现是 LightRAG。

3. LightRAG 每次文档操作都会产生较高的固定开销。

   `LightRAGKnowledgeIndex.index_document()` 通过 `_run_async()` 执行；`_run_async()` 使用全局 `_LIGHTRAG_RUN_LOCK`，在已有事件循环时新建线程和 event loop，并重置共享存储。随后 `_new_rag()` 重新初始化 LightRAG storage，再执行 `ainsert()`，最后 finalize。

4. 多文件 API 是串行调用。

   `POST /agent/knowledge-bases/{kb_id}/documents/import` 逐个调用 `add_existing_document()`；前端 `AssetLibraryWorkspace` 的多文件上传也逐个请求 API。每个文档都会重复复制、解析、SQLite 写入和 LightRAG 初始化。

5. SQLite chunk 是逐行 execute。

   `knowledge_chunks`、`knowledge_file_chunks` 在循环中逐条插入。对大文档会产生不必要的 Python/SQLite 往返。

6. 文件被重复完整读取/复制。

   当前路径包含临时文件写入、`read_bytes()` 计算 SHA256、`shutil.copyfile()` 复制，以及解析阶段再次读取。该项对网络慢上传不是主要瓶颈，但对本地磁盘和大文件有额外成本。

7. 删除/重建也会放大索引成本。

   删除单个文档后 `_rebuild_knowledge_index_sync()` 会清空整个知识库索引，并逐个重新抽取和索引剩余文档。该行为先保留，不在第一、二阶段扩展删除语义，但需要纳入回归和性能基线。

### 2.3 针对“超过 10KB 就卡很久”的专项判断

当前代码没有 `10KB` 的硬编码分支：唯一明确的单文件上限是 `20MB`，本地切片参数是 `MAX_CHUNK_CHARS = 1200`、`CHUNK_OVERLAP_CHARS = 160`。因此“10KB”更像是一个工作量跨越点，而不是文件大小判断条件。

对纯文本粗略估算，10KB 文本在本地切片层面已经会产生约 9～10 个 chunk（实际数量取决于段落边界和中文/英文内容）。同时，LightRAG 接收的是完整文本，可能在内部再次切片；如果配置了远程 LLM/embedding，`ainsert()` 还可能产生 embedding、实体/关系抽取和图/向量写入等多阶段工作。当前这些工作又发生在：

```text
HTTP 请求
  → _add_document_sync()
  → _index_document_best_effort_sync()
  → _run_async()
  → 新线程 + 新 event loop + LightRAG storage 初始化
  → ainsert(完整文档)
```

这会造成“固定初始化成本 + 文档规模成本 + 远程调用成本”的叠加。当文本从几个 chunk 增加到约十个 chunk 后，用户会感觉耗时突然变长。仅凭代码还不能断言主因一定是图谱抽取或 embedding，必须在实现前把以下阶段分别计时：

| 阶段 | 要确认的问题 | 可能的根因 |
| --- | --- | --- |
| 临时文件写入/复制/SHA256 | 是否发生多次完整读写 | 本地 I/O 重复 |
| 文本抽取 | 纯文本是否也耗时，PDF/PPTX 是否占大头 | 解析器或 OCR |
| `_split_chunks` 和 token 计算 | 10KB 前后 chunk 数量、CPU 时间是否突增 | Python 切片/分词 |
| LightRAG 初始化/finalize | 每次是否重新初始化 storage/event loop | 固定框架开销 |
| embedding | 请求次数、批大小、远程等待 | 单 chunk/小批量网络调用 |
| LLM/实体关系抽取 | 是否对每个文档触发额外 LLM 请求 | 图谱构建成本 |
| 文件系统写入 | vdb/kv 文件数量和写入时长 | 索引落盘/锁竞争 |

专项基线必须使用同一份内容模板，分别测试 8KB、10KB、12KB、20KB、50KB；否则无法判断是大小效应还是内容/段落效应。阶段二的“根本提速”验收也必须同时满足：

1. 10KB 以上文档的 HTTP 请求不再等待远程索引；
2. `index_ready_latency` 随文档大小近似线性增长，不出现未解释的数量级跳变；
3. 单位 chunk 的 embedding/LLM 调用次数下降，或明确关闭/延后了非检索必需的图谱工作；
4. 不能通过截断文本、减少 chunk 或静默跳过内容来制造虚假的提速。

实现策略上不把 `10KB` 写成硬编码分支。建议所有上传都采用同一条“先持久化、后处理”协议；10KB 只作为基准测试中的重点拐点，用来验证没有大小相关的异常放大。对于纯文本，即使 10KB 以下也应允许异步索引；对于扫描 PDF，即使文件只有几百 KB，也必须走后台 OCR。

### 2.3.1 本规划的明确决策：异步化和根本提速同时做

这不是“异步化”和“优化算法”二选一：

```text
第一阶段：把阻塞工作移出 API 事件循环，降低本地固定成本
第二阶段：在 chunks 安全落库处切断 HTTP 与 LightRAG，立即返回 indexing
第二阶段的索引 worker：批量 embedding、上下文复用、内容 hash 缓存、快速索引优先
```

只做异步化的方案不合格：如果后台线程仍然为每个文档重新创建 LightRAG、逐个请求 embedding、逐个执行图谱抽取，用户虽然不再看到 HTTP 卡住，但 `index_ready_latency` 和 GPU/远程服务成本仍然很高。

针对当前“10KB 以后卡很久”，阶段二的索引 worker 应按下面的优先级实现：

1. **先让文档可检索。** 优先生成 chunk/向量检索所需的数据；如果当前 LightRAG 版本支持关闭或延后实体—关系抽取，首轮只做向量/文本索引。
2. **再做可选增强。** 图谱实体、关系、摘要等非首轮检索必需的内容作为后台 enrichment，不得阻塞文档进入可检索状态。
3. **没有 vector-only 能力时的兼容路径。** 不假装 LightRAG 已经快速完成；增加轻量的本地 chunk/向量索引作为临时可检索层，LightRAG full index 完成后再切换或合并。查询必须知道自己命中的是 fast index 还是 full index。
4. **批量而不是逐 chunk 调用。** 同一批次的 chunks 通过 embedding provider 的最大安全 batch 发送；按 `content_hash` 去重，重复内容不重复计算 embedding。
5. **复用而不是每文档初始化。** 同一 `kb_id` 的 worker 在生命周期内复用索引上下文；若 LightRAG 共享存储不允许并发，则保持每 KB 单写者，而不是每文档新建线程、event loop、storage。

这样处理后，10KB 文档不会触发特殊分支；它只是从“请求内同步完成所有工作”变为“先完成可靠落库，再由受控 worker 线性处理约 10 个 chunk”。

### 2.3.2 一个 10KB 文档的具体前后对比

以一个约 10KB 的纯文本文件为例，当前实现是：

```text
浏览器上传
  → API 等待临时文件写完
  → API 计算 hash、复制文件、解析、切分约 10 个 chunk
  → API 逐条写 SQLite
  → API 等待 LightRAG 初始化
  → API 等待 embedding /（可能的）LLM 图谱抽取 / 落盘
  → API 返回
```

只要最后两步中任意一步耗时较长，浏览器就一直显示上传中。

阶段一后的过渡行为是：

```text
浏览器上传
  → API 把整段同步工作交给有界 executor
  → API 仍等待 executor 完成
  → 返回 ready/error
```

这能恢复事件循环，但不能解决该请求本身等待 LightRAG 的问题。

阶段二后的目标行为是：

```text
浏览器上传
  → API 流式落盘并创建文档记录
  → API 提交 extraction/index job
  → 立即返回 uploaded/indexing
  → 浏览器继续上传其他文件，不被 LightRAG 阻塞

worker
  → 解析并批量生成约 10 个 chunk
  → 一次或少量批次 embedding
  → fast index ready，文档可检索
  → 后台继续 graph/enrichment（如启用）
```

因此“卡很久”的直接解决点是 HTTP 在 job 提交后结束；“处理本身太慢”的解决点是减少每个文档的初始化、远程请求和非必要图谱工作。两者都必须实现，不能只选其一。

### 2.3.3 后续代码改动的明确落点

规划阶段不修改这些文件；实现阶段预计按以下职责拆分，避免把所有逻辑塞进路由函数：

| 文件/模块 | 计划职责 |
| --- | --- |
| `opentalking/agent/knowledge_store.py` | 保留校验、文件原子落盘、SQLite 元数据/chunk 事务；提供“创建文档记录”和“完成抽取/索引状态”的可组合内部方法 |
| `opentalking/agent/knowledge_index.py` | 增加 batch index 能力、能力探测、索引阶段指标、受控实例/按 KB 锁；不在这里管理 HTTP 生命周期 |
| 新的 knowledge job service/worker | 持久化 job、重试、幂等、按 KB 串行、跨 KB 有界并行、worker 恢复 |
| `apps/api/routes/agent.py` | 保持现有路由；提交 job 并返回可选新增状态字段；不直接等待 LightRAG |
| `apps/api/schemas` | 为文档状态、index phase、progress 和错误信息增加向后兼容字段 |
| `opentalking/runtime` 或独立 worker 入口 | 在 Redis/单进程模式下消费知识库 job；与 speak/init 队列保持可区分的命名空间 |
| `apps/web/src/components/AssetLibraryWorkspace.tsx` | 显示 uploaded/extracting/indexing/ready/error；批量上传不再把每个请求串行等待当作整体进度 |
| `apps/api/tests` | fake index、fake queue、状态/并发/一致性/性能测试 |

实现时先落一个 `KnowledgeIndex` 的 batch/capability 协议，再接入真实 LightRAG；这样可以在没有安装 LightRAG 或没有远程 key 的 CI 中验证上传和 worker 状态。

### 2.4 当前契约和约束

- 支持 `.txt`、`.md`、`.markdown`、`.pdf`、`.pptx`。
- 单文件上限 `20MB`。
- 文档状态包括 `uploaded`、`extracting`、`indexing`、`ready_fast`、`ready` 和 `error`；前端对处理中状态显示明确文案。
- API 返回 `KnowledgeDocumentResponse`，现有客户端依赖 `id`、`status`、`chunk_count`、`error` 等字段。
- SQLite 已启用 WAL 和外键。
- 测试通过 fake `KnowledgeIndex` 隔离真实 LightRAG，不应要求联网或真实 embedding 服务。
- LightRAG 增强失败不会丢失原始文件和 chunks：文档保留为 `ready_fast/index_phase=enrichment`，由 worker 按有限次数重试；只有抽取、chunk 生成或本地落库失败才进入 `error`。
- 本规划不改变检索排序、chunk 算法、文件格式支持范围或 LightRAG 查询语义。

### 2.5 本分支已实现的部分（实现对照）

以下内容已经在 `improve-knowledge-upload` 分支实现，可作为第一、二阶段的当前基线：

| 已实现项 | 具体落点 | 当前语义 |
| --- | --- | --- |
| 有界阻塞执行器 | `KnowledgeStore` 的 async 外观统一调用全局 `ThreadPoolExecutor` | 默认 4 个 worker，可由 `OPENTALKING_KNOWLEDGE_STORE_WORKERS` 调整 |
| 批量 SQLite 写入 | 文档 chunks、文件池 chunks、导入和重索引路径 | 单事务 `executemany()`，保持顺序和回滚 |
| deferred 文档上传 | `add_document_deferred`、`add_existing_document_deferred` | 校验后将 staging 文件原子移动（跨文件系统才 copy），计算内容 hash 并写 `uploaded` 记录，不执行解析和 LightRAG |
| deferred 文件池上传 | `add_file_deferred` + `prepare_file` | 文件池接口立即返回 `uploaded`，后台再解析并生成 file chunks |
| 任务消费者 | `knowledge_index`、`knowledge_index_batch`、`knowledge_prepare_file` | 复用现有 Redis `TASK_QUEUE`；worker 重启会扫描 `uploaded/indexing` 记录恢复任务，解析/索引失败执行有限重试 |
| 调度约束 | task consumer 的按 KB `asyncio.Lock` 与全局 semaphore | 同 KB 串行，跨 KB 默认最多 2 个索引任务，可由 `OPENTALKING_KNOWLEDGE_INDEX_WORKERS` 调整 |
| 批量索引协议 | `KnowledgeIndex.index_documents`、`KnowledgeStore.index_documents`、`knowledge_index_batch` | 文件池多文档导入合并为一个 KB 任务并复用一次 LightRAG 初始化；单文档仍走单任务 |
| embedding 去重/分批 | `LightRAGKnowledgeIndex._embedding_func` 与 `_new_rag` | 按 tokenizer/chunk 版本、模型、维度、最大 token 和文本 hash 做有界 SQLite + 内存缓存；LightRAG embedding batch/concurrency 与 token 总量均受限，默认每批最多 16 条、并发 4，可由 `OPENTALKING_KNOWLEDGE_EMBEDDING_BATCH_SIZE`/`..._BATCH_TOKENS`/`..._CONCURRENCY` 调整 |
| 可诊断状态 | `index_phase`、`retry_count`、`index_error` | 兼容旧 SQLite 自动补列；API/前端可区分 queued、extraction、fast_index、complete、failed |
| 状态查询 | `GET /agent/knowledge-bases/{kb_id}/documents/{doc_id}/status` | 可按单文档轮询，不必重新下载文件；列表接口仍保持兼容 |
| 上传入口覆盖 | 直接上传、文件池、文件池导入、创建知识库时的 files/document_ids | WebUI 先传文件池再建库的路径也不会回到同步索引；创建知识库内的多文件会合并为一个批量任务 |
| 幂等与版本 | Redis `knowledge_index_job_key(kb_id, doc_id)` 使用 NX；任务携带 `generation`/`content_hash` | 同一文档重复提交只保留一个有效排队任务；旧 generation 完成或重试结果会被丢弃 |

`ready_fast` 是可检索状态：当本地 chunks 已成功提交、且 LightRAG 增强仍在执行或失败时，查询
会自动使用本地 chunk 索引，即使未开启旧的 `use_chunk_fallback` 配置。增强重试成功后，状态
再切换为 `ready/index_phase=complete`；因此“增强失败”不会被前端误显示为不可用文档。

当前仍存在的实现边界（不能在验收中忽略）：

1. 对新上传文档，解析仍在 extraction worker 中完成；worker 重试或批量任务会复用已经
   持久化的 SQLite chunks，避免重复 OCR/解析。显式 reindex 会清空旧 chunks 并强制重新
   抽取，避免复用过期内容；后续仍可增加独立文本 artifact 以进一步减少重建时的文件读取。
2. 批量接口目前在 LightRAG 适配器内部复用一次初始化，并向当前版本传入多文档列表（一次
   pipeline）；embedding 是否能在真实 provider 上获得预期合批收益，仍需部署环境压测确认。
3. embedding cache 已持久化到索引根目录的 SQLite，并保留内存 LRU；图谱 enrichment 尚未
   在 LightRAG 内部拆成独立 pipeline，目前通过 `ready_fast` 语义保证本地 chunks 先可检索。
4. `knowledge_index_batch` 的批量 worker 已接入并支持有限重试；任务携带每个文档的
   generation，过期任务会被丢弃。批量失败目前以已存在文档集合重试，API 已返回逐文档
   状态；provider 的部分成功回执和真实 provider 压测仍需继续补齐。
5. 已有 8/10/12/20/50KB 基准脚本和本地 fake-index 结果；真实 LightRAG、远程 embedding
   和 OCR 的生产基准仍待在目标环境执行。

以上边界是从“上传不再卡住”走向“处理本身更快、更可恢复”仍需补齐的工作；不影响当前
`upload_ack` 解耦和 `ready_fast` 可检索语义。

## 3. 目标与非目标

### 3.1 目标

- 上传接口不再被 CPU/磁盘/解析/索引工作长期占用事件循环。
- 上传和索引生命周期可观察、可轮询、可恢复。
- 小文件上传快速返回；大文件和扫描 PDF 不阻塞 HTTP 请求。
- 多文件导入减少重复事务和重复 LightRAG 初始化。
- 索引失败可重试，且不会破坏已成功保存的文档。
- 实时会话与知识库后台处理相互隔离。
- 保持现有 API 路径和现有字段兼容；新增字段采用可选/向后兼容方式。
- 通过单元、API、并发、故障注入和性能基准证明收益。

### 3.2 非目标

- 第一、二阶段不替换 LightRAG 为其他向量数据库。
- 不在本阶段重新设计 chunk 质量、OCR 模型或 embedding 模型。
- 不让索引任务无限并发；远程 embedding/LLM 必须有明确限流。
- 不把“HTTP 很快返回”当作“文档已经可检索”。两者必须由状态字段区分。
- 不在本阶段修改实时数字人渲染、WebRTC、TTS 或模型推理逻辑，除非只增加必要的隔离/指标。

## 4. 阶段一：解除事件循环阻塞并优化本地落库

### 4.1 设计目标

阶段一的核心是“不改变业务语义，只改变执行位置和本地写入效率”。

```text
FastAPI event loop
  ├─ 接收上传、校验请求、调度工作
  └─ await to_thread / bounded executor
       ├─ SHA256、复制、文本解析
       ├─ chunk 切分与 token 计算
       └─ SQLite 事务与批量写入
```

### 4.2 计划内容

#### A. 为同步重工作建立受控执行器

对 `KnowledgeStore` 的 CPU/阻塞操作统一封装到受控线程池或 `asyncio.to_thread`。阶段一允许同步方法整体脱离事件循环；但阶段二不能把这当最终方案，因为“整段 `_add_document_sync()` 放进线程池”仍会让当前 HTTP 请求等待 LightRAG：

- `add_document()`
- `add_file()`
- `add_existing_document()`
- `reindex_document()`
- 删除/重建索引相关操作
- 如查询仍可能触发同步 LightRAG，则查询也必须脱离事件循环

阶段一的实现边界必须写死在 code review 清单中：

- 可以把现有同步路径放到受控 executor，作为无行为变化的过渡；
- 不得宣称这已经缩短了单文档的索引完成时间；
- 第二阶段必须在提交索引任务后结束 HTTP 请求，不能继续 `await` 该 executor future；
- executor 的 worker 数必须小于等于配置上限，并记录排队时间，避免“事件循环不堵但线程池全堵”。

执行器并发数不能直接等于 HTTP 并发数。建议先采用独立的 bounded executor，并通过配置设置最大 worker 数；默认值应保守，避免多个 PDF/OCR 同时消耗所有线程。

#### B. SQLite chunk 使用批量插入

在单个事务内预先生成 rows，然后使用 `executemany()` 写入：

- `knowledge_chunks`
- `knowledge_file_chunks`
- 从文件池导入到知识库的目标 chunks
- 重建索引时的 chunks

同时保持现有唯一性、外键和失败回滚语义。

#### C. 减少一次不必要的文件复制/读取

阶段一只做低风险优化：

- 上传临时文件时计算文件大小和 SHA256，避免再次 `read_bytes()`；
- 在确认跨目录安全和异常清理语义后，优先使用原子 `replace`/rename；不能安全移动时才 copy；
- 解析统一读取最终存储文件，避免为正确性引入第二套文本源。

这项优化必须有跨文件系统 fallback，并保证重复文件检查发生在写入数据库前。

#### D. 保持同步 API 的兼容外观

不修改 `KnowledgeStore` 公共方法名称和返回类型。现有 fake index、路由和前端不需要知道线程池细节。

### 4.3 阶段一的用户体验预期

- 单个纯文本文件：首响应时间可能小幅下降，主要收益是上传期间其他 API、SSE 和实时会话不再被阻塞。
- PDF/PPTX：解析仍需等待当前请求完成，但不会阻塞整个 FastAPI 事件循环；并发请求吞吐提高。
- 扫描 PDF：OCR 仍然可能很慢，阶段一不承诺“秒级完成”。
- 多文件上传：如果只保持现有前端串行请求，总耗时会有一定改善，但不会得到批量索引收益。

### 4.4 阶段一验收标准

- 在一个进程中上传大文本或模拟慢解析时，同时发出的 health、知识库列表和 session SSE 请求仍能在设定 p95 内响应。
- 现有上传、导入、重索引、删除、重复文件和错误文件测试全部通过。
- SQLite chunk 行数、内容、顺序和 `chunk_count` 与改动前一致。
- 发生解析/索引异常时，线程任务不会静默丢失；异常沿原有错误契约返回或写入错误状态。
- 线程池有上限，能够通过配置或测试替换，不创建每次调用一个新的无界 executor。

## 5. 阶段二：上传与索引解耦，增加可恢复的索引任务

### 5.1 设计目标

阶段二将“文档已保存”和“文档已可检索”明确拆分：

```text
HTTP 上传请求
  → 流式写入 staging 文件，同时计算大小/SHA256
  → 基础校验、原子移动到文档目录、写入最小元数据
  → status = uploaded
  → 提交 extraction job
  → 立即返回文档对象

后台 extraction worker
  → 解析文本/OCR
  → 切分 chunks、批量写入 SQLite
  → status = indexing
  → 提交 index job

后台 index worker
  → 获取任务
  → 按知识库串行化，按批次收集 chunks
  → 复用 LightRAG 索引上下文
  → 批量 embedding / vector 写入
  → 非必要 graph/enrichment 延后执行
  → 快速检索索引完成：status = ready（或 ready_fast）
  → 完整增强完成：enrichment_status = ready
  → 失败：status = error + error_code + retry metadata
```

这里的“立即返回”指文件已经安全落盘并且文档元数据已经持久化，不指只在内存中接收后就返回。进程崩溃后，staging 文件必须可以清理或恢复，不能出现 API 返回成功但文件和数据库都不存在的情况。

推荐把抽取也移出 HTTP 请求，而不是只把 LightRAG 移出：对扫描 PDF，OCR 可能比 embedding 更慢；如果仍在请求内做 `_extract_text()`，小文件体验会改善，但 PDF 仍会卡住。对于纯文本，抽取 worker 通常很快；对于 PDF/PPTX，统一使用同一套 job 状态，不再根据扩展名写出另一套不可观察的同步路径。

### 5.1.1 两种“完成”必须分开

阶段二应在数据模型中显式区分：

| 完成点 | 含义 | 用户/API 用途 |
| --- | --- | --- |
| `upload_ack` | 文件和最小文档记录已可靠保存 | 上传按钮解除等待、允许继续操作 |
| `extract_ready` | 文本和 SQLite chunks 已生成 | 展示 chunk 数、允许重试索引 |
| `index_ready` | 首选快速检索索引已可用 | 允许 Agent 检索文档 |
| `enrichment_ready` | 可选图谱/摘要/关系增强已完成 | 提供完整 LightRAG 能力 |

当前“超过 10KB 卡住”的直接用户问题由 `upload_ack` 解决；当前“处理时间太长”的根本问题由 `extract_ready`、`index_ready` 和 `enrichment_ready` 分层后分别优化。任何实现都不能把 `upload_ack` 的降低误报成 `index_ready` 已经变快。

### 5.2 状态模型

建议将文档状态扩展为：

| 状态 | 含义 | 是否可检索 | 可执行动作 |
| --- | --- | --- | --- |
| `uploaded` | 文件已安全落盘，尚未开始抽取 | 否 | 等待/取消 |
| `extracting` | 正在解析文本或 OCR | 否 | 等待/取消 |
| `indexing` | chunks 已落库，快速检索索引正在建立 | 否或只读旧索引 | 等待/重试 |
| `ready_fast` | 本地 chunks 可检索，LightRAG 增强待完成或失败 | 是（自动 chunk fallback） | 查询/等待增强/重试 |
| `ready` | 首选检索索引完成且可查询 | 是 | 查询/重建/删除 |
| `error` | 抽取或索引失败 | 否 | 查看错误/重试/删除 |
| `cancelled`（可选） | 用户或系统取消 | 否 | 重试/删除 |

第一版可以只新增 `indexing`，保留 `ready/error`，但内部必须区分 extraction failure、fast-index failure 和 enrichment failure；否则无法诊断慢点，也无法只重试索引。若暂时不能提供 fast/full 两级索引，至少保留 `index_phase` 或 `enrichment_status`，避免把完整图谱增强混入“文档是否可检索”的单一状态。

### 5.3 API 兼容方案

现有端点保持不变：

- `POST /agent/knowledge-bases/{kb_id}/documents`
- `POST /agent/knowledge-documents`
- `POST /agent/knowledge-bases/{kb_id}/documents/import`
- `POST /agent/knowledge-bases/{kb_id}/documents/{doc_id}/reindex`

响应仍返回 `KnowledgeDocumentResponse`，新增字段建议为可选：

```json
{
  "status": "indexing",
  "chunk_count": 128,
  "index_progress": 0.0,
  "index_error": null,
  "retry_count": 0,
  "updated_at": "..."
}
```

推荐增加一个查询端点或复用现有列表端点轮询状态；如果已有 SSE 事件总线适合承载文档事件，可增加：

- `knowledge.document.status`
- `knowledge.document.ready`
- `knowledge.document.error`

本阶段不强制前端必须改为 SSE；先支持列表轮询，后续再提升交互实时性。

### 5.4 任务队列选择

优先复用 OpenTalking 现有 runtime/Redis 任务基础设施，但知识库索引任务应有独立命名空间和明确幂等键，不应与数字人 speak/init 队列混用到无法区分。

任务至少包含：

```json
{
  "job_id": "kbjob_...",
  "operation": "index_document",
  "kb_id": "...",
  "doc_id": "...",
  "content_hash": "...",
  "attempt": 0,
  "created_at": "..."
}
```

幂等键建议为 `(kb_id, doc_id, content_hash)`；重复提交只能产生一个有效索引任务。若暂时不引入持久化 worker，至少要有应用生命周期内的 bounded queue、后台 task、关闭时 drain/cancel 逻辑，并明确这是单进程能力，不可伪装成生产级分布式队列。

### 5.5 索引执行模型

二阶段不应简单地把现有 `index_document()` 放进后台线程就结束。需要按以下顺序设计：

1. **第一步：后台化。** 上传请求只负责 staging 文件、最小元数据和 index/extraction job 提交；抽取文本、OCR 和 chunks 生成也放到后台 worker，避免 10KB 以上文本或扫描 PDF继续占用请求。
2. **第二步：按知识库串行化。** 同一 `kb_id` 的增删改任务按顺序执行，防止清空/重建和新增索引相互覆盖。
3. **第三步：跨知识库有限并行。** 不同 `kb_id` 可并行，但受 embedding/QPS、CPU 和内存限制。
4. **第四步：批量索引。** worker 收集同一批次的多个文档/chunks，调用 LightRAG 的批量插入或 embedding 批处理接口。
5. **第五步：减少 LightRAG 初始化。** 在 worker 生命周期内复用受控的索引上下文；如果 LightRAG 共享 storage 要求独占，则为每个知识库维护单独 worker/锁，而不是每个文档新建 loop。
6. **第六步：拆分 fast index 和 enrichment。** 首轮只执行让 Agent 能召回文本所需的工作；实体关系、摘要和图谱增强若非当前查询必需，则在文档已经 `ready` 后继续后台执行。
7. **第七步：按内容 hash 复用结果。** 相同内容的文档/重复 chunk 使用 embedding cache；cache key 至少包含 `content_hash`、embedding model、维度和 tokenizer/chunk 版本，版本变化时自动失效。

若 LightRAG 当前版本不支持安全的持久化实例复用、批量接口或关闭图谱抽取，应先做 capability detection。退回“后台逐文档索引”时，只能承诺改善首响应和并发隔离；若同时没有 fast index，则不得把 `ready` 提前到真正可检索之前，也不得宣称已经解决 10KB 以上文档的处理耗时问题。能力检测结果应记录到启动日志和文档索引指标中。

### 5.6 批量上传/导入

需要把两处串行行为纳入二阶段：

- 后端 `create_knowledge_base()` 中的多个 `document_ids` 和多个 `files`；
- 前端 `AssetLibraryWorkspace` 中逐个 POST 的多文件上传。

建议新增内部批量 service，而不是让路由简单 `gather()`：

```text
校验全部输入
  → 计算 hash、检查重复
  → 批量复制/解析（受控并行）
  → 单事务写入文档和 chunks
  → 一次性提交 index batch job
  → 返回各文档状态
```

批量 API 的错误策略需要明确：

- 推荐逐文件结果（成功/重复/格式错误）并保留成功项；
- 创建知识库这一类“整体操作”可以维持全量失败回滚，但不能在后台失败时删除已经上传的文件；
- 前端显示“已上传 n 个，索引中 m 个，失败 k 个”，不要把 `indexing` 误报为失败。

### 5.7 失败、重试和一致性

- 文件落盘成功、SQLite 成功、索引任务提交失败：文档应进入 `error` 或 `index_pending`，而不是消失；提供补偿扫描/重试。
- 索引失败：保留原始文件和 SQLite chunks；清理对应不完整 LightRAG 状态，避免查询到半成品。
- worker 重启：从 `indexing`/`index_pending` 状态恢复未完成任务。
- 同一文档重复重试：先按 doc_id/content_hash 删除或替换旧索引，再写入新索引。
- 删除文档与索引任务竞争：删除操作必须取消/标记过期任务，并保证旧任务不能把已删除文档重新写回索引。
- 重建知识库：使用 generation/version 标记；旧 generation 的晚到结果不得覆盖新 generation。

## 6. “根本提速”拆解

“根本提速”不是单一优化，而是减少每层固定成本和等待范围：

| 层次 | 当前问题 | 一、二阶段方案 | 预期性质 |
| --- | --- | --- | --- |
| HTTP/event loop | 同步工作阻塞请求和所有异步连接 | 受控 executor | 提升并发体验 |
| 文件 I/O | 重复 read/copy | 上传时 hash、原子移动/必要时复制 | 减少磁盘 I/O |
| 解析/OCR | 在请求内同步执行 | 后台 extraction，OCR 限流 | 缩短用户等待，不改变 OCR 算法 |
| SQLite | chunk 逐条写入 | 单事务 `executemany` | 降低本地落库耗时 |
| LightRAG 初始化 | 每文档新 loop/storage/lock | worker 复用上下文、按 KB 串行 | 降低固定开销 |
| Embedding | 文档/请求粒度小批量或重复调用 | chunk/document batch + content hash cache | 降低远程调用和调度开销 |
| 图谱抽取 | 可能和首轮 `ainsert` 混在一起 | fast index 先就绪，graph/enrichment 后置 | 降低首个可检索结果时间 |
| 索引可见性 | HTTP 等待索引完成 | 异步状态机 | 大幅改善感知延迟 |
| 多文档 | 逐个上传、逐个索引 | 批量 service/job | 提升吞吐 |

能真正降低“处理完成时间”的重点是：批量 embedding、LightRAG 上下文复用、content hash 缓存、减少重复解析/复制、同一知识库的增量索引，以及把非首轮检索必需的图谱抽取后置。阶段二必须通过基准分别报告：

- `upload_ack_latency`：上传接口返回时间；
- `extract_ready_latency`：文本/chunk 可用时间；
- `index_ready_latency`：文档可检索时间；
- `batch_throughput`：每分钟完成的文档数和 chunks 数；
- `remote_embedding_calls`：embedding 请求次数和批大小；
- `embedding_cache_hit_rate`：embedding 缓存命中率；
- `fast_index_ready_latency`：首选快速索引可检索时间；
- `enrichment_ready_latency`：完整图谱/摘要增强完成时间；
- `index_stage_breakdown`：初始化、切片、embedding、图谱抽取、落盘各阶段耗时；
- `event_loop_block_p95`：上传期间其他异步请求延迟。

## 7. 测试规划

测试必须同时证明“功能不回归”和“速度改善”。测试不得依赖真实 DashScope、真实 OCR、真实 LightRAG 远程服务或 GPU；真实服务只用于可选的手工 benchmark。

### 7.0 当前已执行的验证

本分支基础实现已完成以下静态和定向验证：

```text
python -m compileall opentalking apps/api
ruff check opentalking apps/api
git diff --check
pytest apps/api/tests/test_agent_knowledge.py -q -k 'deferred or index_job'
```

结果（系统 Python）：定向知识库测试 `37 passed, 2 deselected`；缺少 LightRAG 的系统环境会
使两个既有集成测试失败。结果（项目 `.venv`，包含 `lightrag`/`aiortc`）：知识库测试
`39 passed`，任务消费者测试 `26 passed`，合计 `65 passed`；编译、ruff 和 diff 检查通过。
前端 `npm test` 为 `15 passed`，`npm run typecheck` 通过。上述结果证明功能回归和任务边界，
不等同于远程 embedding/OCR 生产性能达标。

### 7.0.1 当前基准结果（本地 fake index）

使用 `scripts/benchmark_knowledge_upload.py --runs 3`，同一内容模板分别生成 8/10/12/20/50
KiB 文档。脚本将 deferred 上传确认与后台索引分开计时，并用 heartbeat 观察事件循环间隙；
fake index 不访问网络，不能替代真实 LightRAG benchmark。

| 大小 | chunks | upload_ack p50 | baseline 同步 ready p50 | ack 最大事件循环间隙 |
| ---: | ---: | ---: | ---: | ---: |
| 8 KiB | 7 | 10.7 ms | 17.2 ms | 1.9 ms |
| 10 KiB | 8 | 9.3 ms | 17.7 ms | 1.3 ms |
| 12 KiB | 10 | 7.7 ms | 18.3 ms | 1.5 ms |
| 20 KiB | 16 | 9.2 ms | 23.5 ms | 1.7 ms |
| 50 KiB | 39 | 9.7 ms | 51.9 ms | 2.0 ms |

在 `OPENTALKING_BENCHMARK_INDEX_DELAY_MS=100` 的等待模拟下，8–50 KiB 的
`upload_ack_latency` 仍约 10–15 ms，而同步基线约 122–153 ms；这证明 HTTP 没有等待索引
worker。该数字只验证架构边界，不代表真实 embedding/LLM 的生产速度。

对应命令和输出文件：

```text
python scripts/benchmark_knowledge_upload.py --runs 3 --json /tmp/kb-benchmark.json
OPENTALKING_BENCHMARK_INDEX_DELAY_MS=100 \
  python scripts/benchmark_knowledge_upload.py --runs 1 --json /tmp/kb-benchmark-delay.json
```

项目 `.venv` 的后端关键回归现为 `78 passed`（知识库 API/存储、任务消费者及新增批量/重试、
`ready_fast` 保留与自动 chunk fallback 覆盖）；前端为 `15 passed`，TypeScript 类型检查通过。真实 LightRAG 远程 embedding、OCR 和
图谱 enrichment 仍需在部署环境执行专项压测后，才能填写最终吞吐和 `index_ready_latency`
门槛。

### 7.1 阶段一单元测试

建议新增或扩展 `apps/api/tests/test_agent_knowledge.py`，并保持现有 `tests/unit/test_agent_memory.py` 的 fake index 注入方式。

#### 执行调度

1. `test_add_document_runs_blocking_work_off_event_loop`
   - monkeypatch `_add_document_sync` 为带同步事件/短暂阻塞的函数。
   - 在 async 测试中同时运行 heartbeat task。
   - 断言 heartbeat 能持续运行，证明事件循环未被同步函数占满。
2. `test_add_file_and_import_use_bounded_executor`
   - 替换 executor 为可观察 fake executor。
   - 断言任务被调度到 executor，且不会每次调用创建无限线程。
3. `test_executor_failure_preserves_original_exception_contract`
   - worker 抛出 `ValueError`、`DuplicateKnowledgeDocumentError` 和未知异常。
   - 断言路由状态码和错误类型保持现有契约。

#### SQLite 批量落库

1. `test_document_chunks_are_written_in_one_transaction`
   - fake/trace SQLite connection，记录 `executemany` 或事务边界。
   - 断言文档行、chunk 行全部成功或全部回滚。
2. `test_batch_chunk_rows_preserve_order_and_content`
   - 使用短文本、超长段落、中文 token 和 overlap。
   - 断言 chunk 顺序、内容和 `chunk_count` 与现有 `_split_chunks` 一致。
3. `test_partial_chunk_insert_rolls_back_document`
   - 在第 n 个 chunk 写入时注入异常。
   - 断言没有孤立文档或孤立 chunks。

#### 文件 I/O 和重复检查

1. `test_upload_hash_is_not_recomputed_from_multiple_full_reads`（实现若采用单次 hash 才启用）
   - 统计文件读取次数或注入可观察 reader。
2. `test_cross_filesystem_move_falls_back_to_copy`
   - 模拟 rename 失败，断言最终文件完整且临时文件被清理。
3. `test_duplicate_check_happens_before_index_enqueue`
   - 重复上传不得创建第二个文档或索引任务。

### 7.2 阶段一 API/回归测试

基于现有 `apps/api/tests/test_agent_knowledge.py` 保留并扩展：

- 普通 Markdown 上传：状态、文件内容、chunk_count、列表、删除；
- PPTX 上传；
- PDF 成功解析；
- OCR/无文本 PDF 失败；
- 文件池上传与从文件池导入；
- 重复文件返回 409；
- 非法扩展名、空文件、超过 20MB 返回正确错误；
- LightRAG fake index 的 index/delete/clear 调用顺序；
- 上传时并发访问 `/knowledge-bases`、`/health` 或 session 相关只读 API，不出现事件循环阻塞。

### 7.3 阶段二状态机单元测试

建议新增独立测试文件 `apps/api/tests/test_agent_knowledge_index_jobs.py`，避免把 job 行为全部塞入已有大文件。

#### 状态转换

1. `test_upload_transitions_to_indexing_after_chunks_are_committed`
   - mock extraction/index worker 不立即完成。
   - 断言 HTTP 响应已经返回（目标是 `uploaded` 或 `indexing`，由最终状态设计决定），SQLite 最小文档记录已存在。
2. `test_large_text_upload_does_not_await_index_worker`
   - 对 10KB、20KB、50KB 文本让 fake index 永不完成或延迟很久。
   - 断言 POST 在 upload acknowledgement deadline 内返回，后台任务仍可独立完成；不能通过同步等待超时来伪造成功。
3. `test_upload_status_distinguishes_ack_from_index_ready`
   - 记录 `upload_ack`、`extract_ready`、`index_ready` 三个时间点。
   - 断言 API 不把 `upload_ack` 误报为 `ready`。
4. `test_index_worker_transitions_indexing_to_ready`
   - fake index 成功。
   - 断言状态、时间戳和索引状态更新。
5. `test_index_worker_transitions_indexing_to_error_with_retry_metadata`
   - fake index 抛出可重试和不可重试异常。
   - 断言错误码、attempt、next retry 信息正确。
6. `test_recovery_requeues_incomplete_indexing_documents`
   - 初始化时构造 `indexing` 状态和无活动任务。
   - 断言 worker 启动后重新入队。

#### 幂等和并发

1. `test_same_document_job_is_idempotent`
   - 同一 `(kb_id, doc_id, content_hash)` 提交两次。
   - 断言只有一个有效任务/一次最终索引。
2. `test_stale_job_cannot_reindex_deleted_document`
   - 先入队，随后删除，最后让旧任务执行。
   - 断言旧任务被拒绝或结果丢弃。
3. `test_same_knowledge_base_jobs_are_serialized`
   - 两个文档同 KB，记录执行顺序；不得并发破坏索引。
4. `test_different_knowledge_bases_are_bounded_parallel`
   - 多个 KB 并发，断言不超过配置的 worker/embedding 并发上限。
5. `test_rebuild_generation_prevents_late_old_result`
   - 旧重建任务晚于新任务返回；旧结果不得覆盖新 generation。

#### 批量处理

1. `test_batch_import_creates_one_index_batch_job`
   - 导入多个 file pool 文档。
   - 断言不会逐个创建独立初始化流程。
2. `test_batch_import_returns_per_document_results`
   - 混合成功、重复、格式错误输入。
   - 断言每项结果可诊断，成功项不被无关失败回滚（整体创建知识库接口除外）。
3. `test_batch_index_preserves_document_and_chunk_mapping`
   - fake batch index 检查 doc_id、filename、文本映射完整。
4. `test_embedding_batches_respect_provider_limit`
   - 设置明确的 max batch size 和 token 上限。
   - 断言同一批次不会超限，也不会退化成每 chunk 一个远程请求。
5. `test_duplicate_content_reuses_embedding_cache`
   - 两个文档包含相同 chunk/content hash。
   - 断言第二次索引命中 cache，模型、版本或 chunk 参数变化时正确失效。
6. `test_fast_index_can_finish_before_enrichment`
   - fake index 将 vector 和 graph/enrichment 分成两个阶段。
   - 断言文档先进入可检索状态，enrichment 晚完成不会阻塞首轮检索。

### 7.4 阶段二 API 契约测试

1. 旧客户端只读取 `id/status/chunk_count/error` 时仍可工作。
2. 新客户端可以看到 `indexing`，并通过列表或状态端点最终观察到 `ready/error`。
3. 文档在 `uploaded/indexing` 时不会被前端错误标记为“失败”。
4. LightRAG 查询在 `uploaded/indexing` 时返回明确的未就绪原因，而不是静默把空结果当成“没有知识”。
5. 重试端点只允许对失败/未完成文档操作，并保持幂等。
6. API 超时/客户端断开不会取消已成功落盘的后台任务，除非显式使用取消语义。
7. 10KB、12KB、20KB、50KB 的相同模板文档不会因为固定阈值进入隐藏的同步路径。

### 7.5 故障注入测试

必须覆盖以下故障：

- 文本解析异常；
- `pdftotext` 不存在或超时；
- tesseract 超时；
- DashScope OCR 返回 4xx/5xx；
- SQLite busy/锁等待超时；
- LightRAG import 不可用；
- embedding 服务限流/超时/返回格式错误；
- LightRAG 图谱抽取耗时或失败，但 fast index 可以完成；
- embedding cache 版本不匹配或损坏；
- worker 在索引中途退出；
- Redis/任务队列短暂不可用；
- 删除文档时索引任务正在运行；
- API 进程优雅关闭和强制取消。

每个故障都要验证：原始文件是否保留、SQLite 是否一致、状态是否可解释、任务是否可重试、查询是否不会返回半成品。

### 7.6 性能基准和验收门槛

建议新增 `scripts/benchmark_knowledge_upload.py` 或同等测试工具，但在实现阶段再创建；本规划阶段不执行。基准数据集至少包括：

| 数据集 | 规模 |
| --- | --- |
| 小文本 | 10 个，1–10KB |
| 中等 Markdown | 10 个，100KB–1MB |
| 大文本 | 3 个，5–20MB |
| 文本型 PDF | 3 个，10–100 页 |
| 扫描 PDF | 3 个，3–20 页 |
| PPTX | 3 个，10–50 页 |
| 多文件批次 | 10/50 个混合文档 |

每组至少记录 p50/p95/p99：

- 上传接口响应时间；
- 文档进入 `indexing` 时间；
- 文档进入 `ready` 时间；
- 单批吞吐量；
- CPU、RSS、线程数；
- SQLite 写入耗时；
- 解析/OCR耗时；
- LightRAG 初始化、embedding、写入耗时；
- 远程 embedding 请求数、平均 batch size；
- 同时请求 health/session API 的 p95/p99；
- 实时会话首音频/首视频帧是否出现回归。

建议验收门槛（最终数值需先在当前分支基线测量后确认）：

- 阶段一：慢解析/大文件上传期间，健康检查和只读 API 的 p95 不得随上传任务显著抬升；目标是回到无上传基线的 1.5 倍以内。
- 阶段二：小型文本上传接口 p95 目标为“只到落盘/chunk 完成”，不得等待远程索引；目标相对当前同步路径降低至少 70%。
- 阶段二：对 8KB/10KB/12KB/20KB/50KB 相同模板文本，`upload_ack_latency` 不随大小出现数量级跳变；HTTP 请求不等待 index worker。
- 阶段二：若启用 fast index，10KB 以上文档先达到可检索状态，再异步完成 enrichment；两者时间必须分别报告。
- 阶段二：10 个文档批量导入的总 `ready` 时间相对当前逐文档路径降低至少 30%；若没有批量 embedding/实例复用，只报告首响应改善，不宣称达到此目标。
- 失败重试不产生重复文档、重复 chunk 或重复有效索引。
- 不影响现有实时会话的 TTFB、首帧和 interrupt 指标。

上述百分比是工程目标，不是未测量的现状结论；实现前必须先保存 baseline。

## 8. 实施顺序和提交拆分建议

后续实现仍建议保持小提交、可回滚；当前工作区已有阶段一、二的基础实现改动，尚未提交：

1. `docs: add knowledge upload performance plan`：本规划文档（已创建，后续继续维护实现对照）。
2. `perf(knowledge): offload blocking store operations`：阶段一执行器和测试（基础实现已在工作区）。
3. `perf(knowledge): batch sqlite chunk writes`：阶段一批量落库和测试（基础实现已在工作区）。
4. `feat(knowledge): add index job state and worker contract`：阶段二状态/任务抽象和 fake worker 测试（基础实现已在工作区）。
5. `feat(knowledge): decouple upload from lightrag indexing`：阶段二上传响应、异步 reindex、状态更新和有限重试（基础实现已在工作区）。
6. `perf(knowledge): batch index and bounded scheduling`：阶段二批量索引协议、LightRAG 初始化复用和 embedding 分批/cache（基础实现已在工作区；真实 provider 能力仍需验证）。
7. `test(knowledge): add failure and benchmark coverage`：知识库/worker/API/前端类型和基准覆盖（基础实现已在工作区；generation 已覆盖，OCR 故障和真实服务压测待补）。

每个实现提交都应能单独运行对应测试；不要把前端状态、Redis worker、LightRAG 生命周期和 SQLite schema 一次性混在一个不可回滚的大提交中。

## 9. 风险与取舍

### 风险一：后台化后用户以为“上传成功”等于“可检索”

通过 `indexing/ready/error` 状态、前端状态文案和查询未就绪原因解决。API 文档必须明确首响应和可检索完成是两个时间点。

### 风险二：LightRAG 并发不安全

保留每知识库串行化和全局/分片锁；先验证 LightRAG 版本是否支持批量和实例复用，不能仅凭 async 接口名推断线程安全。

### 风险三：任务丢失

任务提交和数据库状态更新需要定义顺序，并增加启动恢复扫描。若使用 Redis，任务 payload 必须含 content hash 和 generation；若只用内存队列，必须明确单进程限制。

### 风险四：索引失败导致查询不一致

SQLite 原始数据与 LightRAG 状态分离；查询只接受 `ready` 索引，失败时保留 chunks 供重试/诊断，不能自动把旧半成品当成新结果。

### 风险五：线程数或远程 QPS 失控

所有并发都要有上限：解析 executor、OCR worker、索引 worker、embedding batch/concurrency。配置需要有安全默认值和日志中的实际并发信息。

### 风险六：删除/重建期间的语义变化

阶段一不改变删除语义；阶段二使用 generation/version 和按 KB 排序，先补测试再优化删除重建。不能为了速度直接取消全量重建而没有一致性证明。

## 10. 需要在实现前确认的问题

这些问题不阻塞规划分支，但实现阶段必须通过代码或依赖版本确认：

1. 当前部署是 API/worker 分进程、unified 单进程，还是两者都需要支持？
2. 生产环境是否已有 Redis 任务队列可供知识库复用？
3. 当前 LightRAG 版本是否支持安全的批量 `ainsert`、批量 embedding 和按 doc_id 删除？
4. embedding provider 的 batch 上限、QPS 和单次 token 上限是多少？
5. 扫描 PDF 是否允许后台 OCR，最大页数和单任务超时是多少？
6. 前端希望采用轮询还是接入 SSE 文档状态事件？
7. `create knowledge base` 的多文件操作是否必须全量事务回滚，还是允许逐文件成功？
8. SQLite 是否继续作为单机/开发存储，生产是否需要迁移到服务化数据库？

## 11. 最终判断

如果用户关心的是“点上传后页面长时间卡住、实时对话同时变慢”，完成第一、二阶段后会有明显、覆盖面很大的改善：第一阶段解除事件循环阻塞，第二阶段让 HTTP 不再等待 LightRAG。

如果用户关心的是“文档什么时候真正能被检索”和“50 个文档的总处理时间”，仅把索引放到后台还不够。必须继续完成批量 embedding、LightRAG 上下文复用、按知识库调度和可恢复任务；这些才是根本降低处理耗时和单位文档成本的部分。

本规划的验收原则是同时报告两类时间：

```text
用户等待时间：upload_ack_latency
系统完成时间：index_ready_latency
```

不能用前者变快来掩盖后者没有改善，也不能为了后者让前者继续阻塞。
