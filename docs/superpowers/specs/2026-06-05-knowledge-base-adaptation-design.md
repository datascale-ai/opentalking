# Knowledge Base Adaptation Design

## Scope

This change adapts the realtime dialogue knowledge-base experience from a single default document bucket to first-class knowledge bases that can be selected per avatar. It also fixes a realtime subtitle state bug where the previous avatar's spoken text can remain under the portrait after switching avatars.

The implementation will preserve compatibility with the existing single `knowledge_base_id` session field and existing document endpoints.

## Requirements

1. Realtime dialogue must show knowledge-base classes in the left knowledge panel, not individual files.
2. A knowledge base can contain one or more uploaded files.
3. The current avatar can select any number of knowledge bases.
4. Selected knowledge bases must appear as removable tags on the right side; removing a tag must also unselect the item in the left list.
5. The knowledge panel must include a Manage button that opens the Asset Library knowledge-base tab.
6. The Asset Library must include a Knowledge Bases tab that lists all knowledge bases.
7. The Asset Library must include a New Knowledge Base action. The creation modal is titled "新建知识库", accepts a name, and manages an initial file list.
8. At least one file is required before a knowledge base can be created.
9. The knowledge-base file area must support upload, delete, and reindex operations. Online file content editing is out of scope because the current backend stores uploaded files and generated chunks, not editable source documents.
10. The Asset Library must include a placeholder button for importing local intermediate files such as LightRAG output. This button will show a "future adaptation" notice for now.
11. Avatar knowledge-base selection must persist per avatar.
12. Session creation must support multiple selected knowledge bases while still accepting the old single `knowledge_base_id`.
13. Retrieval must query all selected knowledge bases and merge the best matching chunks.
14. Switching avatar/model/session state must clear stale portrait subtitle text.

## Backend Design

### Storage

`KnowledgeStore` will add a `knowledge_bases` table:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

It will also add an avatar selection table:

- `avatar_id TEXT NOT NULL`
- `kb_id TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- primary key on `(avatar_id, kb_id)`

Existing `knowledge_documents` and `knowledge_chunks` remain the source of document metadata and retrieval chunks. Existing rows with `kb_id = "default"` remain valid. Initialization will ensure a `default` knowledge-base row exists when default documents exist or when the store is initialized.

Knowledge base IDs will continue to use the existing safe ID constraints. The API can generate IDs from names plus a short unique suffix, avoiding fragile display-name-as-ID behavior.

### Store Methods

`KnowledgeStore` will add:

- `list_knowledge_bases()`
- `create_knowledge_base(name: str)`
- `rename_knowledge_base(kb_id: str, name: str)`
- `delete_knowledge_base(kb_id: str)`
- `query_many(kb_ids: list[str], query: str, limit: int = 3)`
- `get_avatar_knowledge_bases(avatar_id: str)`
- `set_avatar_knowledge_bases(avatar_id: str, kb_ids: list[str])`

Document methods remain scoped by `kb_id`. The API layer will create the knowledge-base row first, then call the existing document upload path once per uploaded file. If any initial file fails, creation returns an error and removes the partially created knowledge base and files.

`query_many` will fetch ready chunks for all selected knowledge bases, score them with the existing token-overlap scoring, sort by score descending, and return the top chunks. Empty selection returns no chunks.

### API

Existing document endpoints remain:

- `GET /agent/knowledge-bases/{kb_id}/documents`
- `POST /agent/knowledge-bases/{kb_id}/documents`
- `DELETE /agent/knowledge-bases/{kb_id}/documents/{doc_id}`
- `POST /agent/knowledge-bases/{kb_id}/documents/{doc_id}/reindex`

Knowledge-base endpoints will be added:

- `GET /agent/knowledge-bases`
- `POST /agent/knowledge-bases`
- `PATCH /agent/knowledge-bases/{kb_id}`
- `DELETE /agent/knowledge-bases/{kb_id}`

Avatar selection endpoints will be added:

- `GET /agent/avatars/{avatar_id}/knowledge-bases`
- `PUT /agent/avatars/{avatar_id}/knowledge-bases`

`POST /agent/knowledge-bases` accepts a name and one or more uploaded files via multipart form data. Creation fails with 400 if no files are provided or the name is empty.

`GET /agent/knowledge-bases` returns rich objects, including ID, name, document count, ready document count, error document count, and timestamps. This replaces the current string-only response shape for new frontend code. Compatibility will be handled in tests and frontend call sites in this branch.

### Session Compatibility

`CreateSessionRequest` will add:

- `knowledge_base_ids: list[str] | None`

It will keep:

- `knowledge_base_id: str | None`

Normalization rules:

1. If `knowledge_base_ids` is provided and non-empty, use the sanitized unique list.
2. Else if `knowledge_base_id` is provided, use `[knowledge_base_id]`.
3. Else default to `["default"]`.

The task payload, task consumer, `AgentSessionConfig`, `SessionRunner`, and `FlashTalkRunner` will carry `knowledge_base_ids`. They may also include `knowledge_base_id` as a compatibility mirror where existing tests or consumers still expect it.

## Frontend Design

### Realtime Dialogue

`AgentConfig` changes from a single `knowledgeBaseId` to `knowledgeBaseIds`.

Avatar selection drives knowledge selection:

1. On avatar change, load that avatar's persisted knowledge-base IDs.
2. Show all available knowledge bases in the knowledge panel left list.
3. Selecting an item toggles its ID in the current avatar's selection.
4. Persist the updated selection through `PUT /agent/avatars/{avatar_id}/knowledge-bases`.
5. Show selected knowledge bases as tags on the right. Removing a tag updates the same selection state and persists it.

The Manage button switches the main workflow to Asset Library and opens the Knowledge Bases tab.

### Asset Library

Add a `knowledge` tab to `AssetLibraryWorkspace`.

The tab lists all knowledge bases with:

- name
- document count
- ready/error count
- updated time
- actions for rename/delete
- expandable or selected file list

The New Knowledge Base button opens a modal titled "新建知识库" with:

- name input
- file picker
- pending file list
- remove file action before creation
- create button disabled until name is non-empty and at least one file is selected

After creation, the tab refreshes the knowledge-base list.

The LightRAG/import button is a placeholder. It does not parse files yet; it only shows a user notice that import adaptation is planned.

### Subtitle Bug Fix

Realtime state cleanup will clear all subtitle state when avatar/model/session context changes:

- `currentSubtitle`
- `subtitleAccRef`
- `subtitleMediaReadyRef`
- subtitle fallback timer
- streaming assistant message reference
- pending assistant message reference

This prevents the previous avatar's spoken text from remaining under the portrait after switching avatars.

## Testing

Backend tests:

- Knowledge-base list/create/rename/delete.
- Knowledge-base creation rejects empty name and zero files.
- Existing document upload/list/delete/reindex still works.
- Avatar selection get/set persists per avatar.
- Session creation accepts `knowledge_base_ids`.
- Session creation still accepts legacy `knowledge_base_id`.
- Context building queries multiple knowledge bases and merges results.

Frontend tests:

- Realtime knowledge panel shows knowledge bases rather than documents.
- Selecting/unselecting knowledge bases updates selected tags.
- Removing a tag unselects the left list item.
- Manage button opens Asset Library knowledge tab.
- New knowledge-base modal requires at least one file.
- Avatar switch loads separate persisted selections.
- Avatar switch clears stale subtitle text.

Verification:

- `pytest apps/api/tests tests`
- `mypy opentalking/core opentalking/events opentalking/avatar apps/api apps/unified apps/cli --ignore-missing-imports`
- frontend test command used by this repository, if available from package scripts.

## Migration And Compatibility

The migration is lazy and SQLite-backed through `KnowledgeStore.initialize()`. No external migration tool is required.

The old default knowledge-base documents remain in place under `data/knowledge/default/documents`. Existing users who never create new knowledge bases continue to use `default`.

The session API remains backward compatible with old clients sending `knowledge_base_id`.
