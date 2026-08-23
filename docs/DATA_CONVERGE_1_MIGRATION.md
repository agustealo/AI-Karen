# DATA-CONVERGE-1 Migration Guide

## Overview

DATA-CONVERGE-1 retires Milvus, Elasticsearch, legacy vector clients, duplicate conversation stores, duplicate DB adapters, and standalone attachment helpers by absorbing their responsibilities into PostgreSQL + pgvector + FTS + Supabase Storage.

## Audit Classification

| Component | Classification | Action |
|-----------|---------------|--------|
| `memory_items` table (PostgreSQL) | **CANONICAL** | Extend with tenant_id, embedding_vector, FTS |
| `conversations` + `messages` tables | **CANONICAL** | Add tenant_id, converge chat_conversations |
| `memory_event` + `memory_assertion` (ledger) | **KEEP** | Governance layer, not retrieval |
| Milvus client + MilvusWorker | **RETIRE** | Replace with pgvector via MemoryRepository |
| Elasticsearch client + ElasticWorker | **RETIRE** | Replace with PostgreSQL FTS via MemoryRepository |
| Zvec API service + routes | **RETIRE** | Replace with canonical MemoryRepository |
| DuckDB worker | **KEEP** | OLAP tier, not being retired |
| Redis worker | **KEEP** | STM / cache / ephemeral runtime |
| `FileAttachmentService` | **RETIRE** | Replace with ArtifactStore |
| `DatabaseClient` / `MultiTenantPostgresClient` | **CONVERGE** | One connection authority |
| `DatabaseServiceFactory` | **KEEP** | Wiring layer, simplify internals |
| `ConversationManager` | **MIGRATE** | Delegate to ConversationRepository |
| `MemoryManager` | **MIGRATE** | Delegate to MemoryRepository |

## Staged Migration Plan

### Stage 1: Schema (DONE)
- [x] Migration 008: pgvector extension, memory_items extensions, FTS trigger, indexes
- [x] Migration 009: tenant_id on conversations, chat_conversations, indexes

### Stage 2: Backfill
```bash
# Backfill embedding_vector from legacy embedding arrays
python -m ai_karen_engine.database.migrations.backfill_embeddings

# Backfill tenant_id on conversations from auth_users
python -m ai_karen_engine.database.migrations.backfill_conversation_tenants
```

### Stage 3: Parity Validation
```bash
# Compare Milvus recall with PostgreSQL recall
python -m ai_karen_engine.services.database.migration_validator --compare memory

# Compare Elasticsearch lexical search with PostgreSQL FTS
python -m ai_karen_engine.services.database.migration_validator --compare search

# Validate conversation counts match
python -m ai_karen_engine.services.database.migration_validator --compare conversations
```

### Stage 4: Shadow Reads
Canonical repositories run in shadow mode alongside legacy systems:
```python
# In MemoryRuntimeManager or MemoryManager:
if settings.DATA_CONVERGE_SHADOW_MODE:
    canonical_results = await memory_repo.search_hybrid(query, embedding)
    legacy_results = await legacy_milvus_search(...)
    log_comparison(canonical_results, legacy_results)
```

### Stage 5: Canonical Read Switch
Enable canonical repositories for reads:
```python
KARI_MEMORY_BACKEND=postgres
KARI_CONVERSATION_BACKEND=postgres
KARI_ARTIFACT_BACKEND=supabase
```

### Stage 6: Canonical Write Switch
Route new writes to canonical repositories. Legacy systems receive no new data.

### Stage 7: Freeze Legacy
Set feature flags to disable Milvus, Elasticsearch, Zvec:
```python
KARI_ENABLE_VECTOR_DB=false
KARI_ENABLE_ELASTICSEARCH=false
KARI_ENABLE_ZVEC=false
```

### Stage 8: Reference Audit
Search codebase for remaining references to retired systems:
```bash
rg "MilvusClient|ElasticClient|ZvecApiService|MilvusWorker|ElasticWorker" src/
```

### Stage 9: Delete Legacy
Remove retired code after zero references remain.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KARI_ENABLE_VECTOR_DB` | `true` | **RETIRING**: Set to `false` to disable Milvus |
| `KARI_ENABLE_ELASTICSEARCH` | `true` | **RETIRING**: Set to `false` to disable Elasticsearch |
| `KARI_ENABLE_ZVEC` | `true` | **RETIRING**: Set to `false` to disable Zvec |
| `KARI_MEMORY_BACKEND` | `legacy` | Set to `postgres` for canonical reads |
| `KARI_CONVERSATION_BACKEND` | `legacy` | Set to `postgres` for canonical reads |
| `KARI_ARTIFACT_BACKEND` | `legacy` | Set to `supabase` for canonical artifact storage |
| `DATA_CONVERGE_SHADOW_MODE` | `false` | Set to `true` for shadow reads during migration |

## Acceptance Gates

Milvus and Elasticsearch do not disappear until ALL gates pass:

### Retrieval
- [ ] Recall@K >= existing Milvus recall
- [ ] NDCG/MRR >= existing where available
- [ ] P95 latency acceptable
- [ ] Tenant filtering correct
- [ ] Metadata filtering correct

### Data
- [ ] Record counts match across systems
- [ ] Embedding counts match
- [ ] Orphan count = 0
- [ ] Conversation counts match
- [ ] Attachment checksum mismatches = 0

### Security
- [ ] Cross-tenant tests pass
- [ ] RBAC tests pass
- [ ] RLS tests pass
- [ ] Service-role audit passes

### Recovery
- [ ] Backup tested
- [ ] Restore tested
- [ ] Migration rollback exercised

## Repository Usage

### Memory
```python
from ai_karen_engine.services.database.repositories import RepositoryFactory, MemoryQuery

factory = RepositoryFactory(session_factory=async_session_factory)
memory_repo = factory.create_memory_repository()

# Store memory
item = MemoryItem(
    id=str(uuid.uuid4()),
    tenant_id=tenant_id,
    user_id=user_id,
    content="User prefers dark mode",
    memory_type="profile",
    embedding=embedding_vector,
)
result = await memory_repo.store_memory(item)

# Semantic search
query = MemoryQuery(tenant_id=tenant_id, user_id=user_id, top_k=10)
results = await memory_repo.search_semantic(query, embedding=query_embedding)

# Hybrid search
results = await memory_repo.search_hybrid(query, embedding=query_embedding)
```

### Conversations
```python
from ai_karen_engine.services.database.repositories import (
    RepositoryFactory,
    ConversationQuery,
    Message,
)

factory = RepositoryFactory(session_factory=async_session_factory)
conv_repo = factory.create_conversation_repository()

# Create conversation
conv = Conversation(
    id=str(uuid.uuid4()),
    tenant_id=tenant_id,
    user_id=user_id,
    title="New Chat",
)
result = await conv_repo.create_conversation(conv)

# Add message
msg = Message(
    id=str(uuid.uuid4()),
    conversation_id=conv.id,
    tenant_id=tenant_id,
    role="user",
    content="Hello",
)
await conv_repo.add_message(msg)

# List conversations
query = ConversationQuery(tenant_id=tenant_id, user_id=user_id, limit=20)
convs = await conv_repo.list_conversations(query)
```

### Artifacts
```python
from ai_karen_engine.services.database.repositories import (
    RepositoryFactory,
    ArtifactUploadRequest,
)

factory = RepositoryFactory(
    session_factory=async_session_factory,
    storage_client=supabase_client,
)
artifact_store = factory.create_artifact_store()

# Upload
request = ArtifactUploadRequest(
    tenant_id=tenant_id,
    user_id=user_id,
    conversation_id=conv_id,
    filename="report.pdf",
    content_type="application/pdf",
    data=file_bytes,
)
result = await artifact_store.upload(request)

# Download
result = await artifact_store.download(artifact_id, tenant_id)
```

## Rollback

If canonical repositories fail during Stage 5 or 6:

```bash
# Revert environment variables
KARI_MEMORY_BACKEND=legacy
KARI_CONVERSATION_BACKEND=legacy
KARI_ARTIFACT_BACKEND=legacy

# Re-enable legacy systems
KARI_ENABLE_VECTOR_DB=true
KARI_ENABLE_ELASTICSEARCH=true

# Restart application
```

PostgreSQL remains the durable source of truth. Rollback only affects the read/write path, not the data.

## Timeline

| Week | Stage | Deliverable |
|------|-------|-------------|
| 1 | 1-2 | Schema migrations deployed, backfill jobs run |
| 2 | 3-4 | Parity validation passes, shadow mode enabled |
| 3 | 5-6 | Canonical read/write switch, legacy disabled |
| 4 | 7-9 | Legacy code removed, cleanup complete |
