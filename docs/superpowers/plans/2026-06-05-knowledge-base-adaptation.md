# Knowledge Base Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build first-class multi-file knowledge bases, persist selected knowledge bases per avatar, pass multiple knowledge bases into realtime sessions, and clear stale subtitles when switching avatars.

**Architecture:** Extend the existing SQLite-backed `KnowledgeStore` instead of introducing a new RAG engine. Preserve current document endpoints and legacy `knowledge_base_id`, while adding rich knowledge-base metadata, avatar selection endpoints, and `knowledge_base_ids` through the session pipeline. Frontend state moves from a single default document list to knowledge-base summaries plus per-avatar selected IDs.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLite, pytest, mypy, React, TypeScript, Vite.

---

## File Structure

- Modify `opentalking/agent/knowledge_store.py`: add knowledge-base metadata table, avatar selection table, summary dataclass, CRUD methods, and multi-KB retrieval.
- Modify `opentalking/agent/context_builder.py`: change config to carry `knowledge_base_ids` while keeping compatibility.
- Modify `apps/api/schemas/session.py`: add `knowledge_base_ids` to session creation request.
- Modify `apps/api/routes/sessions.py`: normalize single/multiple knowledge-base fields and pass both compatibility fields to session service.
- Modify `apps/api/services/session_service.py`: accept and enqueue `knowledge_base_ids`.
- Modify `opentalking/runtime/task_consumer.py`: parse `knowledge_base_ids` and pass to runners.
- Modify `opentalking/pipeline/session/runner.py` and `opentalking/pipeline/speak/synthesis_runner.py`: accept and store multi-KB agent config.
- Modify `apps/api/routes/agent.py`: add knowledge-base CRUD and avatar selection endpoints; keep document endpoints.
- Modify `apps/api/tests/test_agent_knowledge.py`: cover knowledge-base CRUD, initial files, avatar selection, and multi-KB query.
- Modify `apps/api/tests/test_sessions.py`: cover `knowledge_base_ids` and legacy `knowledge_base_id`.
- Modify `tests/unit/test_agent_memory.py` or add `tests/unit/test_agent_context_builder.py`: cover multi-KB context building if not already covered elsewhere.
- Modify `apps/web/src/lib/api.ts`: add knowledge-base summary and selection types.
- Modify `apps/web/src/components/AvatarSelectionStage.tsx`: replace single knowledge config with multi-KB selected tags and manage button entry point.
- Modify `apps/web/src/components/AssetLibraryWorkspace.tsx`: add Knowledge Bases tab, list, creation modal, file upload/delete/reindex, and LightRAG import placeholder.
- Modify `apps/web/src/App.tsx`: load/persist per-avatar KB selection, pass `knowledge_base_ids` to session creation, clear subtitle state on avatar/model/session changes, and route asset library to knowledge tab.
- Modify or add frontend tests under `tests/frontend/`: cover knowledge panel behavior, asset library tab entry, create modal gating, and stale subtitle clearing.

---

### Task 1: Backend Knowledge Store Data Model

**Files:**
- Modify: `opentalking/agent/knowledge_store.py`
- Test: `apps/api/tests/test_agent_knowledge.py`

- [ ] **Step 1: Write failing tests for knowledge-base summaries and avatar selection**

Add tests to `apps/api/tests/test_agent_knowledge.py`:

```python
async def test_knowledge_store_lists_created_knowledge_bases(tmp_path: Path) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
    await store.initialize()

    created = await store.create_knowledge_base(name="产品知识库")
    bases = await store.list_knowledge_bases()

    assert created.name == "产品知识库"
    assert any(item.id == created.id and item.document_count == 0 for item in bases)
    assert any(item.id == "default" and item.name == "Default" for item in bases)


async def test_knowledge_store_persists_avatar_knowledge_selection(tmp_path: Path) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
    await store.initialize()
    product = await store.create_knowledge_base(name="产品知识库")
    support = await store.create_knowledge_base(name="售后知识库")

    saved = await store.set_avatar_knowledge_bases(
        avatar_id="singer",
        kb_ids=[product.id, support.id, product.id],
    )
    loaded = await store.get_avatar_knowledge_bases(avatar_id="singer")

    assert saved == [product.id, support.id]
    assert loaded == [product.id, support.id]
    assert await store.get_avatar_knowledge_bases(avatar_id="other") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/tests/test_agent_knowledge.py::test_knowledge_store_lists_created_knowledge_bases apps/api/tests/test_agent_knowledge.py::test_knowledge_store_persists_avatar_knowledge_selection -q`

Expected: FAIL because `KnowledgeStore.create_knowledge_base`, `list_knowledge_bases`, `set_avatar_knowledge_bases`, and `get_avatar_knowledge_bases` do not exist.

- [ ] **Step 3: Implement store metadata**

In `opentalking/agent/knowledge_store.py`, add dataclass:

```python
@dataclass(frozen=True)
class KnowledgeBaseSummary:
    id: str
    name: str
    document_count: int
    ready_document_count: int
    error_document_count: int
    created_at: str
    updated_at: str
```

Update `_initialize_sync()` to create `knowledge_bases` and `avatar_knowledge_bases`, plus a default row:

```python
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS knowledge_bases (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """
)
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS avatar_knowledge_bases (
      avatar_id TEXT NOT NULL,
      kb_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY(avatar_id, kb_id),
      FOREIGN KEY(kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
    )
    """
)
now = _utc_now()
conn.execute(
    """
    INSERT INTO knowledge_bases(id, name, created_at, updated_at)
    VALUES ('default', 'Default', ?, ?)
    ON CONFLICT(id) DO NOTHING
    """,
    (now, now),
)
```

Add async wrappers and sync helpers:

```python
async def create_knowledge_base(self, *, name: str) -> KnowledgeBaseSummary:
    return self._create_knowledge_base_sync(name)

async def list_knowledge_bases(self) -> list[KnowledgeBaseSummary]:
    return self._list_knowledge_bases_sync()

async def get_avatar_knowledge_bases(self, *, avatar_id: str) -> list[str]:
    return self._get_avatar_knowledge_bases_sync(avatar_id)

async def set_avatar_knowledge_bases(self, *, avatar_id: str, kb_ids: list[str]) -> list[str]:
    return self._set_avatar_knowledge_bases_sync(avatar_id, kb_ids)
```

Use `_safe_kb_id`, `_new_id("kb")`, `_utc_now()`, and SQL joins to implement summaries. Validate non-empty names. Deduplicate selected IDs while preserving order. Reject unknown selected KB IDs with `ValueError("knowledge base not found")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/tests/test_agent_knowledge.py::test_knowledge_store_lists_created_knowledge_bases apps/api/tests/test_agent_knowledge.py::test_knowledge_store_persists_avatar_knowledge_selection -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add opentalking/agent/knowledge_store.py apps/api/tests/test_agent_knowledge.py
git commit -m "feat: add knowledge base metadata store"
```

---

### Task 2: Backend Knowledge API

**Files:**
- Modify: `apps/api/routes/agent.py`
- Test: `apps/api/tests/test_agent_knowledge.py`

- [ ] **Step 1: Write failing route tests**

Add tests:

```python
async def test_agent_knowledge_base_routes_create_list_and_avatar_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    async with LifespanManager(api_app):
        transport = ASGITransport(app=api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/agent/knowledge-bases", data={"name": "产品知识库"})
            assert response.status_code == 400

            response = await client.post(
                "/agent/knowledge-bases",
                data={"name": "产品知识库"},
                files=[("files", ("product.txt", b"hello product", "text/plain"))],
            )
            assert response.status_code == 200
            created = response.json()
            assert created["name"] == "产品知识库"
            assert created["document_count"] == 1

            listed = await client.get("/agent/knowledge-bases")
            assert listed.status_code == 200
            assert any(item["id"] == created["id"] for item in listed.json()["knowledge_bases"])

            selected = await client.put(
                "/agent/avatars/singer/knowledge-bases",
                json={"knowledge_base_ids": [created["id"]]},
            )
            assert selected.status_code == 200
            assert selected.json()["knowledge_base_ids"] == [created["id"]]

            loaded = await client.get("/agent/avatars/singer/knowledge-bases")
            assert loaded.status_code == 200
            assert loaded.json()["knowledge_base_ids"] == [created["id"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/tests/test_agent_knowledge.py::test_agent_knowledge_base_routes_create_list_and_avatar_selection -q`

Expected: FAIL because the new routes do not exist.

- [ ] **Step 3: Implement route models and endpoints**

In `apps/api/routes/agent.py`, add Pydantic models:

```python
class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    document_count: int
    ready_document_count: int
    error_document_count: int
    created_at: str
    updated_at: str


class KnowledgeBasesResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseResponse]


class AvatarKnowledgeBasesRequest(BaseModel):
    knowledge_base_ids: list[str]


class AvatarKnowledgeBasesResponse(BaseModel):
    knowledge_base_ids: list[str]
```

Change `GET /knowledge-bases` response to `KnowledgeBasesResponse`. Add `POST /knowledge-bases` with `name: str = Form(...)` and `files: list[UploadFile] = File(...)`; reject zero files. Create the base, upload each file through `KnowledgeStore.add_document`, and return the refreshed summary. Add avatar GET/PUT endpoints.

- [ ] **Step 4: Run tests**

Run: `pytest apps/api/tests/test_agent_knowledge.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/routes/agent.py apps/api/tests/test_agent_knowledge.py
git commit -m "feat: add knowledge base api routes"
```

---

### Task 3: Multi-KB Session Pipeline

**Files:**
- Modify: `opentalking/agent/knowledge_store.py`
- Modify: `opentalking/agent/context_builder.py`
- Modify: `apps/api/schemas/session.py`
- Modify: `apps/api/routes/sessions.py`
- Modify: `apps/api/services/session_service.py`
- Modify: `opentalking/runtime/task_consumer.py`
- Modify: `opentalking/pipeline/session/runner.py`
- Modify: `opentalking/pipeline/speak/synthesis_runner.py`
- Test: `apps/api/tests/test_sessions.py`
- Test: `apps/api/tests/test_agent_knowledge.py`

- [ ] **Step 1: Write failing tests**

Add/adjust tests:

```python
async def test_context_builder_queries_multiple_knowledge_bases(tmp_path: Path) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
    await store.initialize()
    product = await store.create_knowledge_base(name="产品")
    support = await store.create_knowledge_base(name="售后")
    product_file = tmp_path / "product.txt"
    support_file = tmp_path / "support.txt"
    product_file.write_text("AlphaProduct supports warranty", encoding="utf-8")
    support_file.write_text("BetaSupport handles refunds", encoding="utf-8")
    await store.add_document(kb_id=product.id, filename="product.txt", mime_type="text/plain", source_path=product_file)
    await store.add_document(kb_id=support.id, filename="support.txt", mime_type="text/plain", source_path=support_file)

    prompt = await build_agent_context(
        user_id="u",
        avatar_id="a",
        latest_user_text="warranty refunds",
        config=AgentSessionConfig(agent_enabled=True, memory_enabled=False, knowledge_enabled=True, knowledge_base_ids=[product.id, support.id]),
        memory_store=None,
        knowledge_store=store,
    )

    assert "AlphaProduct" in prompt
    assert "BetaSupport" in prompt
```

In `apps/api/tests/test_sessions.py`, add:

```python
def test_create_session_passes_multiple_knowledge_bases_to_service(monkeypatch: pytest.MonkeyPatch, unified_client: TestClient) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*_args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        return "sess_multi_kb"

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)
    monkeypatch.setattr(task_consumer, "slot_is_occupied", lambda: False)

    response = unified_client.post(
        "/sessions",
        json={
            "avatar_id": "singer",
            "model": "mock",
            "knowledge_base_ids": ["kb_a", "kb_b"],
            "knowledge_enabled": True,
        },
    )

    assert response.status_code == 200
    assert calls[0]["knowledge_base_ids"] == ["kb_a", "kb_b"]
    assert calls[0]["knowledge_base_id"] == "kb_a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/tests/test_agent_knowledge.py::test_context_builder_queries_multiple_knowledge_bases apps/api/tests/test_sessions.py::test_create_session_passes_multiple_knowledge_bases_to_service -q`

Expected: FAIL because multi-KB fields are not implemented.

- [ ] **Step 3: Implement multi-KB retrieval**

Add `KnowledgeStore.query_many(kb_ids: list[str], query: str, limit: int = 3)`. Deduplicate IDs, sanitize, use SQL `WHERE c.kb_id IN (...) AND d.status = 'ready'`, score with the same token-overlap logic, and return top chunks.

Update `AgentSessionConfig`:

```python
knowledge_base_id: str | None = "default"
knowledge_base_ids: list[str] | None = None
```

Add a property that returns normalized IDs. `build_agent_context` should call `query_many` when more than one ID is present and fall back to `query` for compatibility if needed.

- [ ] **Step 4: Implement API/session normalization**

Add `knowledge_base_ids: list[str] | None = None` to `CreateSessionRequest`.

In `apps/api/routes/sessions.py`, normalize:

```python
def _normalize_knowledge_base_ids(body: CreateSessionRequest) -> list[str]:
    raw_ids = body.knowledge_base_ids or ([body.knowledge_base_id] if body.knowledge_base_id else ["default"])
    result: list[str] = []
    for raw in raw_ids:
        kb_id = str(raw or "").strip()
        if kb_id and kb_id not in result:
            result.append(kb_id)
    return result or ["default"]
```

Pass `knowledge_base_ids=knowledge_base_ids` and `knowledge_base_id=knowledge_base_ids[0]` to service/task payload. Update service, task consumer, and both runner constructors to accept and forward the list.

- [ ] **Step 5: Run tests**

Run: `pytest apps/api/tests/test_agent_knowledge.py apps/api/tests/test_sessions.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add opentalking/agent/knowledge_store.py opentalking/agent/context_builder.py apps/api/schemas/session.py apps/api/routes/sessions.py apps/api/services/session_service.py opentalking/runtime/task_consumer.py opentalking/pipeline/session/runner.py opentalking/pipeline/speak/synthesis_runner.py apps/api/tests/test_agent_knowledge.py apps/api/tests/test_sessions.py
git commit -m "feat: pass multiple knowledge bases through sessions"
```

---

### Task 4: Frontend Knowledge API State

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/App.tsx`
- Test: `tests/frontend/test_quicktalk_send_path.py` or new frontend test file

- [ ] **Step 1: Add frontend types**

In `apps/web/src/lib/api.ts`, add:

```ts
export type KnowledgeBaseSummary = {
  id: string;
  name: string;
  document_count: number;
  ready_document_count: number;
  error_document_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeBasesResponse = {
  knowledge_bases: KnowledgeBaseSummary[];
};

export type AvatarKnowledgeBasesResponse = {
  knowledge_base_ids: string[];
};
```

- [ ] **Step 2: Update App state**

In `App.tsx`, replace default document-only state with:

```ts
const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([]);
const [selectedKnowledgeBaseIds, setSelectedKnowledgeBaseIds] = useState<string[]>([]);
const [knowledgeLoading, setKnowledgeLoading] = useState(false);
const [knowledgeUploading, setKnowledgeUploading] = useState(false);
```

Add functions:

```ts
const refreshKnowledgeBases = useCallback(async () => {
  setKnowledgeLoading(true);
  try {
    const response = await apiGet<KnowledgeBasesResponse>("/agent/knowledge-bases");
    setKnowledgeBases(response.knowledge_bases);
  } finally {
    setKnowledgeLoading(false);
  }
}, []);

const loadAvatarKnowledgeSelection = useCallback(async (targetAvatarId: string) => {
  const response = await apiGet<AvatarKnowledgeBasesResponse>(
    `/agent/avatars/${encodeURIComponent(targetAvatarId)}/knowledge-bases`,
  );
  setSelectedKnowledgeBaseIds(response.knowledge_base_ids);
}, []);
```

Persist selection with `PUT /agent/avatars/{avatar_id}/knowledge-bases`. Send `knowledge_base_ids: selectedKnowledgeBaseIds` in `/sessions` payload.

- [ ] **Step 3: Run frontend type check/test command**

Run the repository frontend test command if present in `package.json`; otherwise run `npm --prefix apps/web run build`.

Expected: PASS after downstream components are updated in the next tasks. If this task alone fails because props are not updated yet, keep the failure as expected and proceed.

- [ ] **Step 4: Commit after component tasks pass**

Commit is delayed until Tasks 5 and 6 because `App.tsx` prop changes need component updates to compile.

---

### Task 5: Realtime Knowledge Panel UI And Subtitle Cleanup

**Files:**
- Modify: `apps/web/src/components/AvatarSelectionStage.tsx`
- Modify: `apps/web/src/App.tsx`
- Test: `tests/frontend/test_default_model_selection.py` or new frontend test file

- [ ] **Step 1: Update component props**

In `AvatarSelectionStage.tsx`, change `AgentConfig`:

```ts
export type AgentConfig = {
  memoryEnabled: boolean;
  knowledgeEnabled: boolean;
  knowledgeBaseIds: string[];
};
```

Add props:

```ts
knowledgeBases: KnowledgeBaseSummary[];
selectedKnowledgeBaseIds: string[];
onKnowledgeSelectionChange: (ids: string[]) => void;
onManageKnowledgeBases: () => void;
```

- [ ] **Step 2: Implement UI**

Add a knowledge panel next to the avatar selection area using current Tailwind style:

- Header "知识库"
- Manage button "管理"
- Left list of knowledge-base buttons with selected state
- Right selected tags with `×` remove buttons
- Empty state "未选择知识库"

Toggle logic:

```ts
const toggleKnowledgeBase = (id: string) => {
  const exists = selectedKnowledgeBaseIds.includes(id);
  onKnowledgeSelectionChange(
    exists ? selectedKnowledgeBaseIds.filter((item) => item !== id) : [...selectedKnowledgeBaseIds, id],
  );
};
```

- [ ] **Step 3: Clear subtitle state on context changes**

In `App.tsx`, add a central helper:

```ts
const clearSubtitleState = useCallback(() => {
  subtitleAccRef.current = "";
  subtitleMediaReadyRef.current = false;
  clearSubtitleFallbackTimer();
  streamingAssistantMsgIdRef.current = null;
  pendingAssistantMsgIdRef.current = null;
  setCurrentSubtitle("");
  setIsSpeaking(false);
}, [clearSubtitleFallbackTimer]);
```

Call it in `resetLiveState`, avatar change handler, model change handler, and before creating a new session.

- [ ] **Step 4: Run frontend verification**

Run: `npm --prefix apps/web run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/AvatarSelectionStage.tsx apps/web/src/App.tsx apps/web/src/lib/api.ts
git commit -m "feat: add realtime knowledge base selection"
```

---

### Task 6: Asset Library Knowledge Tab

**Files:**
- Modify: `apps/web/src/components/AssetLibraryWorkspace.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Add active-tab prop support**

In `AssetLibraryWorkspace.tsx`, change:

```ts
type AssetTab = "exports" | "knowledge" | "avatars" | "voices";
```

Add props:

```ts
initialTab?: AssetTab;
activeTabOverride?: AssetTab | null;
onActiveTabChange?: (tab: AssetTab) => void;
```

Wire `App.tsx` Manage button to set workflow to asset library and selected tab to `knowledge`.

- [ ] **Step 2: Add knowledge tab list and actions**

Use `apiGet<KnowledgeBasesResponse>("/agent/knowledge-bases")` to load bases. For selected KB, load `GET /agent/knowledge-bases/{kb_id}/documents`. Show counts, timestamps, and actions.

Add document actions using existing endpoints:

```ts
await apiDelete(`/agent/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(documentId)}`);
await apiPost<KnowledgeDocument>(`/agent/knowledge-bases/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(documentId)}/reindex`);
```

- [ ] **Step 3: Add new knowledge-base modal**

Modal state:

```ts
const [createOpen, setCreateOpen] = useState(false);
const [newKnowledgeName, setNewKnowledgeName] = useState("");
const [newKnowledgeFiles, setNewKnowledgeFiles] = useState<File[]>([]);
```

Create request:

```ts
const form = new FormData();
form.set("name", newKnowledgeName.trim());
for (const file of newKnowledgeFiles) form.append("files", file);
await apiPostForm<KnowledgeBaseSummary>("/agent/knowledge-bases", form);
```

Disable create unless `newKnowledgeName.trim()` is non-empty and `newKnowledgeFiles.length > 0`.

- [ ] **Step 4: Add LightRAG placeholder**

Add button "从本地中间文件导入" that calls `onNotify?.("LightRAG 中间文件导入后续适配。", "info")`.

- [ ] **Step 5: Run frontend build**

Run: `npm --prefix apps/web run build`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/AssetLibraryWorkspace.tsx apps/web/src/App.tsx apps/web/src/lib/api.ts
git commit -m "feat: add asset library knowledge management"
```

---

### Task 7: Full Verification And PR Cleanup

**Files:**
- Modify as needed based on failures.

- [ ] **Step 1: Run backend tests**

Run: `pytest apps/api/tests tests`

Expected: PASS.

- [ ] **Step 2: Run mypy**

Run: `mypy opentalking/core opentalking/events opentalking/avatar apps/api apps/unified apps/cli --ignore-missing-imports`

Expected: PASS.

- [ ] **Step 3: Run frontend build/test**

Run: `npm --prefix apps/web run build`

Expected: PASS.

- [ ] **Step 4: Inspect git state**

Run: `git status --short --branch`

Expected: branch `feat/knowledge-base-adaptation` with no uncommitted changes after final fixes are committed.

- [ ] **Step 5: Push branch**

Run: `git push -u origin feat/knowledge-base-adaptation`

Expected: branch pushed for manual upstream PR.

---

## Coverage Review

- Requirements 1-5 are covered by Tasks 4 and 5.
- Requirements 6-10 are covered by Task 6.
- Requirements 11-13 are covered by Tasks 1-3.
- Requirement 14 is covered by Task 5.
- Backend verification is covered by Task 7.
- Frontend verification is covered by Tasks 5-7.
