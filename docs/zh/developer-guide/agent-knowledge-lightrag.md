# Agent 知识库 LightRAG 改造说明

本文说明本次知识库检索改造涉及的核心代码逻辑。改造目标是保留现有知识库、文件池、角色绑定和前端 API 形态，同时优先使用 LightRAG 检索。普通对话路径默认只使用 LightRAG；SQLite chunk/token overlap 兜底逻辑保留，但必须通过配置显式打开。LightRAG-only 诊断接口始终不走兜底，用来单独证明 LightRAG 是否真正生效。

## 涉及文件

- `opentalking/agent/knowledge_index.py`
  - 新增 LightRAG 适配层。
  - 对外暴露统一的 `KnowledgeIndex` 协议和 `LightRAGKnowledgeIndex` 实现。
- `opentalking/agent/knowledge_store.py`
  - 继续负责知识库元数据、文件落盘、PDF/文本抽取、状态维护。
  - 上传、导入、重建、删除、查询时调用 `KnowledgeIndex`。
- `apps/api/schemas/session.py`
  - 增加实时会话知识库切换请求和响应模型。
- `apps/api/services/session_service.py`
  - 增加运行中 session 的知识库选择更新逻辑，写回 Redis 并通知 worker。
- `apps/api/routes/sessions.py`
  - 增加 `POST /sessions/{session_id}/knowledge-bases`。
- `opentalking/runtime/task_consumer.py`
  - 支持 worker 收到知识库切换任务后更新已加载 runner。
- `apps/web/src/App.tsx`
  - 前端切换知识库后同步当前实时会话。
- `apps/web/src/components/SettingsPanel.tsx`
  - 实时对话进行中仍允许切换已就绪知识库。
- `apps/web/src/lib/api.ts`
  - 增加 session 知识库切换 API 类型。
- `opentalking/core/config.py`
  - 增加 LightRAG 相关配置字段。
- `.env.example`
  - 增加 LightRAG 配置示例。
- `pyproject.toml`
  - 增加 `lightrag-hku` 依赖。
- `apps/api/tests/test_agent_knowledge.py`
  - 增加 LightRAG 索引、查询、导入、删除重建相关测试。
- `tests/unit/test_agent_memory.py`
  - 调整 Agent 上下文测试，显式使用 fake LightRAG 索引。

## 总体架构

现有知识库逻辑被拆成两层：

1. `KnowledgeStore`
   - 管文件。
   - 管 SQLite 元数据。
   - 管文档状态、chunk_count、知识库列表、角色绑定。
   - 优先把检索交给索引层；LightRAG 无结果时默认返回空，只有显式打开配置时才走本地 chunk 兜底排序。

2. `KnowledgeIndex`
   - 管索引。
   - 管查询。
   - 默认实现是 `LightRAGKnowledgeIndex`。

这样做的结果是：前端和 API 不需要大改，原来的上传知识库、导入文件、删除知识库、选择知识库流程都还能用；对话时会先查询 LightRAG，LightRAG 没有返回内容时默认不再回退旧的 SQLite token overlap 检索。需要保留旧行为时，可以通过配置显式打开 fallback。

## LightRAG 适配层

新增文件 `opentalking/agent/knowledge_index.py` 是本次改造的核心。

### `KnowledgeIndex`

`KnowledgeIndex` 是一个协议，定义 `KnowledgeStore` 需要的索引能力：

```python
class KnowledgeIndex(Protocol):
    def index_document(...): ...
    def delete_document(...): ...
    def clear_knowledge_base(...): ...
    def query(...) -> list[LightRAGSearchResult]: ...
    def status(...) -> LightRAGStatus: ...
```

测试里可以注入 fake index，真实运行时默认使用 LightRAG。这样单元测试不需要联网，也不需要真实模型服务。

### `LightRAGKnowledgeIndex`

`LightRAGKnowledgeIndex` 每个知识库使用独立工作目录：

```text
data/knowledge/_lightrag/<kb_id>/
```

核心方法：

- `index_document`
  - 文档有可抽取文本时调用。
  - 内部创建 `LightRAG(...)`。
  - 调用 `initialize_storages()` 初始化存储。
  - 调用 `ainsert(text, ids=[doc_id], file_paths=[filename])` 写入文档。

- `delete_document`
  - 如果当前 LightRAG 版本支持 `adelete_by_doc_id`，就按文档 ID 删除。

- `clear_knowledge_base`
  - 删除该知识库对应的 LightRAG 工作目录。
  - 用于删除知识库、重建索引。

- `query`
  - 调用 `aquery(query, param=QueryParam(...))`。
  - 返回 `LightRAGSearchResult`，再由 `KnowledgeStore` 转成原有 `KnowledgeChunk` 结构，保持上下游兼容。

LightRAG 是懒加载的：代码只有真正索引或查询时才 import `lightrag`。如果运行环境还没安装 `lightrag-hku`，上传和元数据流程不会崩。普通对话查询默认只看 LightRAG 结果；LightRAG-only 诊断接口会直接返回 `available=false`、`reason=lightrag_not_installed`，不会回退。

## KnowledgeStore 的变化

`KnowledgeStore` 构造函数新增可选参数：

```python
KnowledgeStore(
    db_path=...,
    knowledge_root=...,
    knowledge_index=...,  # 测试或自定义索引用
    use_chunk_fallback=False,  # 显式打开后才使用 SQLite token overlap 兜底
)
```

如果没有传 `knowledge_index`，会通过 `default_knowledge_index()` 创建默认 LightRAG 索引。

### 上传文档

`add_document` 的流程现在是：

1. 校验文件。
2. 复制到知识库目录。
3. 抽取文本。
4. 用 `_split_chunks` 计算 `chunk_count`，继续写入 SQLite，兼容前端状态展示。
5. 如果文档状态是 `ready`，调用：

```python
self.knowledge_index.index_document(
    kb_id=kb_id,
    doc_id=doc_id,
    filename=filename,
    text=text,
)
```

注意：SQLite 的 `knowledge_chunks` 表仍会写入，它用于历史兼容、计数、文件池导入，以及显式开启 fallback 后的普通对话兜底检索。默认情况下，LightRAG 无结果时不会查询 `knowledge_chunks`。

### 从文件池导入

`add_existing_document` 的流程现在是：

1. 从 `knowledge_files` 找到源文件。
2. 复制一份到目标知识库目录。
3. 复制源文件对应的 chunk 元数据到 `knowledge_chunks`。
4. 如果源文件是 `ready`，把 chunk 文本合并后写入 LightRAG。

这样文件池上传和知识库导入仍复用原有元数据，同时目标知识库会拥有自己的 LightRAG 索引。

### 重新索引

`reindex_document` 的流程现在是：

1. 重新从原文件抽取文本。
2. 更新 SQLite 中的文档状态和 `chunk_count`。
3. 删除 LightRAG 中对应 doc_id。
4. 如果重新抽取成功，再把新文本写回 LightRAG。

这解决了 OCR 失败后重新索引的场景。

### 删除文档

删除单个知识库文档后，现在会调用：

```python
self._rebuild_knowledge_index_sync(kb_id)
```

重建逻辑是：

1. 清空该知识库的 LightRAG 工作目录。
2. 从 SQLite 找出该知识库剩余的 `ready` 文档。
3. 重新抽取每个文档文本。
4. 逐个写回 LightRAG。

这样比只删一个 doc 更稳，因为不同 LightRAG 版本的文档级删除能力可能不同；重建能保证索引和数据库最终一致。

### 删除知识库

删除知识库时除了删除原有文档目录和 SQLite 记录，还会调用：

```python
self.knowledge_index.clear_knowledge_base(kb_id)
```

也就是一起清掉该知识库的 LightRAG 索引目录。

### 查询知识库

旧逻辑是：

1. 对用户 query 分词。
2. 从 `knowledge_chunks` 查所有 chunk。
3. 计算 token overlap 分数。
4. 返回分数最高的 chunk。

新逻辑是：

1. 校验 `kb_id` 和 query。
2. 读取 ready 文档的 `doc_id -> filename` 映射，用于展示 source。
3. 调用：

```python
results = self.knowledge_index.query(kb_id=kb_id, query=query, limit=safe_limit)
```

4. 把 `LightRAGSearchResult` 转成原来的 `KnowledgeChunk`。
5. 如果 LightRAG 没有返回内容，默认直接返回空；只有 `agent_lightrag_chunk_fallback_enabled=true` 时，才使用旧的 `knowledge_chunks` token overlap 兜底。

因此 `context_builder.py` 和 `prompt.py` 不需要改，Agent Context 仍然吃 `KnowledgeChunk`。默认配置下普通对话路径也只接受 LightRAG 结果；如果显式打开 fallback，这条路径就不能单独证明 LightRAG 生效，因为结果可能来自 SQLite chunk 兜底。

如果要恢复旧的 token/chunk 兜底行为，启动 API 前设置：

```bash
export OPENTALKING_AGENT_LIGHTRAG_CHUNK_FALLBACK_ENABLED=true
```

### 实时会话中切换知识库

实时对话界面仍然可以切换知识库，并且下一轮用户输入会使用最新选择。

数据流：

```text
前端点击知识库
  -> App.setAgentConfig
  -> POST /sessions/{session_id}/knowledge-bases
  -> session_service.update_agent_knowledge_bases
  -> Redis session hash 写入 knowledge_base_id / knowledge_base_ids / knowledge_enabled
  -> worker 任务 update_agent_knowledge_bases
  -> runner.agent_config 更新
  -> 下一次 build_agent_context 只查询当前选择的 kb_ids
```

行为约束：

- 未选择任何知识库时，`knowledge_base_ids=[]`，`knowledge_enabled=false`，不会查询旧知识库，也不会回退默认知识库。
- `AgentSessionConfig.has_knowledge` 同时要求已开启 Agent、已开启知识库、且至少选中一个知识库；取消到 0 个时不会调用 `KnowledgeStore.query_many()`。
- 新选择的知识库会写入当前 session，下一轮文本输入、语音识别后的文本输入都会使用新选择。
- 前端只允许选择 `ready_document_count > 0` 的知识库；实时会话进行中不再锁死知识库按钮。
- 如果 worker 尚未完成 runner 初始化，初始化时会从 Redis session hash 读取最新知识库选择，避免使用 init 任务里的旧值。

### LightRAG-only 诊断查询

新增诊断接口：

```http
POST /agent/knowledge-bases/{kb_id}/lightrag/query
```

请求体：

```json
{"query": "我部署卡住了，训练也卡住了", "limit": 3}
```

响应体：

```json
{
  "available": false,
  "indexed": false,
  "reason": "lightrag_not_installed",
  "results": []
}
```

这个接口只调用：

```python
store.knowledge_index.status(kb_id=kb_id)
store.knowledge_index.query(kb_id=kb_id, query=query, limit=limit)
```

它不会调用 `KnowledgeStore.query()` 或 `KnowledgeStore.query_many()`，所以不会触发 SQLite `knowledge_chunks` 兜底。要验证 LightRAG 本身是否召回了内容，以这个接口的 `results` 为准。

## 配置逻辑

新增配置字段：

```python
agent_lightrag_root
agent_lightrag_query_mode
agent_lightrag_llm_base_url
agent_lightrag_llm_api_key
agent_lightrag_llm_model
agent_lightrag_embedding_base_url
agent_lightrag_embedding_api_key
agent_lightrag_embedding_model
agent_lightrag_embedding_dim
agent_lightrag_embedding_max_token_size
agent_lightrag_language
agent_lightrag_chunk_fallback_enabled
```

默认行为：

- `agent_lightrag_root` 为空时，使用：

```text
<agent_knowledge_root>/_lightrag
```

- LightRAG LLM 配置默认复用项目已有：

```text
OPENTALKING_LLM_BASE_URL
OPENTALKING_LLM_API_KEY
OPENTALKING_LLM_MODEL
```

- embedding 配置默认也复用 LLM base_url/api_key，但 model 默认是：

```text
text-embedding-v4
```

`.env.example` 中增加了对应配置示例。

- `agent_lightrag_chunk_fallback_enabled` 默认为 `false`。设为 `true` 时，`KnowledgeStore.query()` 和 `query_many()` 在 LightRAG 无结果时会查询 SQLite `knowledge_chunks`，恢复旧 token overlap 兜底行为。

## 测试策略

测试没有直接启动真实 LightRAG，也没有依赖外部模型服务，而是用 `FakeKnowledgeIndex` 验证 `KnowledgeStore` 是否正确调用索引层。

覆盖点包括：

- ready 文档上传后会写入 LightRAG index。
- 普通查询优先走 LightRAG，默认在 LightRAG 未返回时不回退 SQLite token overlap；同时覆盖了显式打开兜底后的兼容路径。
- 实时会话中切换知识库会同步 session 和 runner；未选择知识库时不会查询旧知识库。
- LightRAG-only 诊断接口只走 `knowledge_index`，不会回退 SQLite chunk。
- 文件池文档导入知识库后会写入目标知识库的 LightRAG index。
- 删除单文档后会重建该知识库的 LightRAG index。
- 删除知识库后会清理 LightRAG index。
- Agent Context 能拿到 LightRAG 返回内容。
- `OPENTALKING_AGENT_LIGHTRAG_*` 环境变量能被 `Settings` 正确读取。

## 兼容边界

- API 路由和前端知识库管理流程保持原样。
- SQLite 元数据表仍保留，避免破坏已有文件列表、状态、chunk_count、知识库统计。
- 普通对话检索默认不保留 SQLite chunk 兜底，只使用 LightRAG；`OPENTALKING_AGENT_LIGHTRAG_CHUNK_FALLBACK_ENABLED=true` 可显式恢复旧兜底。
- LightRAG-only 诊断接口不回退 SQLite chunk；未安装 `lightrag-hku` 时会返回 `reason=lightrag_not_installed`。
- `uv.lock` 当前在仓库 `.gitignore` 中，不作为本次变更文件；依赖通过 `pyproject.toml` 声明。

## 最终数据流

上传文档：

```text
前端上传
  -> API route
  -> KnowledgeStore.add_document
  -> 文件落盘 + 文本抽取 + SQLite 元数据
  -> LightRAGKnowledgeIndex.index_document
  -> data/knowledge/_lightrag/<kb_id>
```

对话检索：

```text
用户发起对话
  -> build_agent_context
  -> KnowledgeStore.query_many
  -> LightRAGKnowledgeIndex.query
  -> 默认只返回 LightRAG 结果
  -> 如 LightRAG 无结果且 fallback 显式开启，再查 SQLite knowledge_chunks
  -> KnowledgeChunk
  -> prompt.py 注入 <knowledge_base>
  -> LLM 回答
```

实时切换知识库：

```text
实时对话界面选择知识库
  -> POST /sessions/{session_id}/knowledge-bases
  -> Redis session hash 更新 knowledge_base_ids
  -> worker 更新 runner.agent_config
  -> 下一轮对话按新的 knowledge_base_ids 查询 LightRAG
```

LightRAG-only 诊断：

```text
POST /agent/knowledge-bases/{kb_id}/lightrag/query
  -> LightRAGKnowledgeIndex.status
  -> LightRAGKnowledgeIndex.query
  -> results 或 reason
```

删除文档：

```text
删除知识库文档
  -> SQLite 删除文档记录和 chunk 记录
  -> 删除原文件
  -> 清空该知识库 LightRAG index
  -> 重建剩余 ready 文档 index
```
