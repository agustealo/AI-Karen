# MEMORY-CLOSURE-1 Tenant Isolation End-to-End Verification

## Objective
Prove the ChatRuntime → memory gateway → storage adapter → PostgreSQL → vector/search indexes chain preserves tenant_id/user_id/conversation_id boundaries.

## Chain Analysis

### 1. ChatRuntime Layer
**Entry Point:** ChatRuntime.get_memory_manager()

Based on live repo inspection, ChatRuntime already passes:
- 	enant_id
- user_id 
- conversation_id

**Key Questions to Verify:**
- Where does ChatRuntime obtain these identifiers?
- Are they consistently passed through all memory operations?
- Is there any path where identities get dropped or defaulted?

### 2. Memory Gateway Layer
**Canonical Facade:** unified_memory_service.py

**Data Models:**
- MemoryCommitRequest requires user_id (min_length=1)
- MemoryQueryRequest requires user_id (min_length=1)  
- Both include optional org_id for tenant scoping

**Verification Points:**
- Are tenant/user IDs always validated before memory operations?
- Is there any anonymous fallback in the unified service?
- How does the service handle missing identity?

### 3. Storage Adapter Layer
**Database Layer:** database/memory_manager.py and MultiTenantPostgresClient

**Models:** MemoryEntry, MemoryManager, MemoryQuery

**Verification Points:**
- Do SQL queries always include WHERE tenant_id = ? AND user_id = ?
- Are there any queries that scope by conversation_id only?
- Is there any risk of cross-tenant data leakage?

### 4. PostgreSQL Layer  
**Repository:** persistence/repositories/SqlMemoryRepository

**Schema Verification Needed:**
- Confirm memory tables have proper tenant_id/user_id foreign keys
- Check for missing indexes on identity columns
- Verify RLS (Row Level Security) policies if present

### 5. Vector/Search Index Layer
**Vector Stores:** Milvus, Elasticsearch

**Critical Question:** Do vector embeddings preserve tenant/user metadata?

**Risks:**
- Vector similarity search could return cross-tenant results if metadata filtering is missing
- Embeddings might be stored without proper scoping
- Search indexes might not include tenant/user filters

## Call Path Tracing

### Memory Write Path:
`
ChatRuntime.get_memory_manager(tenant_id, user_id, conversation_id)
    ↓
unified_memory_service.commit(MemoryCommitRequest)
    ↓
memory_writeback.system.process_interaction()
    ↓
persistence.repositories.SqlMemoryRepository.store()
    ↓
PostgreSQL INSERT with tenant_id/user_id
    ↓
Vector index update with tenant metadata
`

### Memory Read Path:
`
ChatRuntime.get_memory_manager(tenant_id, user_id, conversation_id)
    ↓
unified_memory_service.query(MemoryQueryRequest) 
    ↓
retrieval.curated_recall.build_curated_metadata_filter()
    ↓
PostgreSQL SELECT with WHERE tenant_id = ? AND user_id = ?
    ↓
Vector similarity search with tenant filter
    ↓
Result filtering by tenant/user context
`

## Gaps and Risky Spots to Investigate

### High Priority Gaps:
1. **Vector index tenant filtering** - Need to verify Milvus/Elasticsearch queries include tenant metadata filters
2. **Anonymous fallback elimination** - Check if any path defaults missing identities to \
anonymous\
3. **Conversation-only scoping** - Look for queries that use conversation_id without tenant/user

### Medium Priority Gaps:
4. **Cache invalidation** - Ensure STM/episodic caches respect tenant boundaries
5. **Projection scoping** - Verify memory projections maintain tenant isolation
6. **Migration scripts** - Check if database migrations properly enforce constraints

### Low Priority Gaps:
7. **Analytics queries** - Ensure cross-tenant analytics properly aggregate
8. **Debug/admin interfaces** - Verify admin tools don't bypass tenant checks

## SQL Query Scoping Verification

### Expected Pattern:
`sql
SELECT * FROM memory_entries 
WHERE tenant_id = :tenant_id 
  AND user_id = :user_id
  AND (conversation_id = :conversation_id OR conversation_id IS NULL)
`

### Risky Patterns to Find:
`sql
-- Missing tenant scoping
SELECT * FROM memory_entries WHERE user_id = :user_id

-- Missing user scoping  
SELECT * FROM memory_entries WHERE tenant_id = :tenant_id

-- Conversation-only (risky)
SELECT * FROM memory_entries WHERE conversation_id = :conversation_id
`

## Testing Strategy

### Unit Tests:
1. Verify unified service rejects requests without user_id
2. Test that memory queries never return cross-tenant data
3. Confirm vector search applies tenant filters

### Integration Tests:
1. End-to-end write/read with different tenants
2. Verify conversation isolation within same tenant
3. Test user isolation within same tenant/conversation

### Security Tests:
1. Attempt to read another tenant's memory (should fail)
2. Try to write without proper identity (should reject)
3. Vector search for cross-tenant similar content (should not return)

## Constraints
- All work stays within: core/memory/, services/memory/, persistence/, storage/, 	ests/core/memory/, 	ests/persistence/
- DO NOT modify chat_runtime.py during this sprint
- No edits - only discovery and reporting
- Focus on finding gaps, not fixing them

## Success Criteria
- ✅ Complete call path documentation from ChatRuntime to storage
- ✅ SQL query pattern analysis for all memory operations
- ✅ Vector index tenant filtering verification
- ✅ Identified list of risky spots needing fixes
- ✅ Gap prioritization with severity ratings
