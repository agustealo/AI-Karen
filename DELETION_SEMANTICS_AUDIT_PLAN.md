# MEMORY-CLOSURE-1 Deletion Semantics Audit

## Objective
Audit memory deletion paths to ensure a canonical deletion invalidates records across PostgreSQL, vector index, search index, STM cache, and projections. Find orphaned-index risks.

## Deletion Path Components

### 1. PostgreSQL Canonical Records
**Primary Store:** `persistence/repositories/SqlMemoryRepository`
**Tables:** `memory_entries`, `memory_episodes`, `memory_assertions`, `contradiction_events`

**Deletion Operations:**
- `delete_memory_entry(memory_id)` - Should cascade to all related records
- `delete_by_conversation(conversation_id)` - Bulk deletion for conversation cleanup
- `delete_by_user(user_id)` - User data deletion (GDPR compliance)

**Risks:**
- Missing CASCADE constraints in foreign keys
- Soft deletes vs hard deletes inconsistency
- Transaction rollback during multi-step deletion

### 2. Vector Index Entries
**Vector Stores:** Milvus, Elasticsearch
**Indexing:** Memory embeddings stored with metadata references

**Critical Question:** When a PostgreSQL record is deleted, does the vector entry get removed?

**Risks:**
- Orphaned vector entries (deleted from Postgres but still in vector index)
- Vector similarity search returning deleted memory
- Metadata filter failures causing cross-contamination
- Async deletion delays causing temporary inconsistency

**Current Pattern Analysis Needed:**
- Does unified_memory_service.delete() call vector index cleanup?
- Is there a background job to clean orphaned vector entries?
- Are vector deletions transactional with Postgres deletions?

### 3. Search Index Entries  
**Search Engine:** Elasticsearch (if present)
**Indexing:** Full-text search indexes with memory content

**Risks:**
- Search index not updated on memory deletion
- Deleted content still searchable via full-text
- Index refresh delays causing stale results

**Verification Needed:**
- Does memory deletion trigger search index updates?
- Is there a sync vs async deletion strategy?
- How are search index errors handled?

### 4. STM Cache
**Short-Term Memory:** `core/memory/stm/`
**Caching:** In-memory cache of recent memory operations

**Risks:**
- Cache not invalidated on deletion
- Deleted memory still returned from cache
- Cache coherency issues across multiple instances

**Verification Needed:**
- Does deletion invalidate STM cache entries?
- Is there a cache key pattern that includes memory IDs?
- How are cache misses handled after deletion?

### 5. Projections
**Derived Views:** `core/memory/projections/`
**Projections:** Curated memories, aggregated views, analytics

**Risks:**
- Projections not updated on source deletion
- Stale projection data referencing deleted memory
- Projection rebuild failures

**Verification Needed:**
- Do projections subscribe to deletion events?
- Is there a projection rebuild strategy?
- How are projection consistency checks performed?

## Orphaned-Index Risks to Find

### High Severity Risks:
1. Vector index orphans - Deleted Postgres records still in Milvus/Elasticsearch
2. Search index ghosts - Full-text search returns deleted content
3. Cache staleness - STM cache returning deleted memory

### Medium Severity Risks:
4. Projection inconsistency - Derived views showing deleted data
5. Async deletion gaps - Temporary windows where indexes are inconsistent
6. Cascade failures - Partial deletion leaving some components updated

### Low Severity Risks:
7. Analytics lag - Reporting systems showing deleted data temporarily
8. Backup inconsistencies - Deleted data still in recent backups

## Delete Gate Contract Proposal

### Canonical Delete Method:
```python
class UnifiedMemoryService:
    async def delete(self, delete_request: MemoryDeleteRequest) -> DeleteResult:
        """
        Atomically delete memory across all storage layers.
        
        Guarantees:
        1. PostgreSQL record deleted (or soft-deleted)
        2. Vector index entry removed
        3. Search index entry removed  
        4. STM cache invalidated
        5. Projections marked stale or updated
        
        Transaction semantics:
        - Either all components succeed or all fail
        - No partial deletion states
        - Retryable transient failures
        """
```

### Required Layers:
1. Coordination Layer - Orchestrates deletion across components
2. Transaction Manager - Ensures atomicity across storage systems
3. Compensation Logic - Handles partial failures with rollback
4. Validation Layer - Pre-deletion checks (ownership, permissions)
5. Audit Layer - Log all deletion operations for compliance

### Implementation Options:

**Option A: Distributed Transaction**
- Use 2PC across Postgres, vector stores, cache
- Strong consistency but high complexity
- May impact performance

**Option B: Eventual Consistency with Compensation**
- Delete from Postgres first (source of truth)
- Fire events to clean up other systems
- Background reconciliation for orphaned entries
- Better performance but temporary inconsistency

**Option C: Hybrid Approach**
- Strong consistency for critical path (Postgres + cache)
- Eventual consistency for secondary indexes (vector, search)
- Periodic cleanup jobs for orphans
- Balance of consistency and performance

## Current Implementation Analysis Needed

### Files to Audit:
1. `core/memory/unified_memory_service.py` - Find delete() implementation
2. `core/memory/memory_writeback.py` - Check writeback deletion handling
3. `persistence/repositories/SqlMemoryRepository.py` - Verify Postgres deletion
4. `core/memory/stm/` - Check cache invalidation
5. `core/memory/projections/` - Verify projection updates
6. Storage adapter implementations for Milvus/Elasticsearch

### Questions to Answer:
1. Is there a canonical delete() method in unified_memory_service?
2. Does deletion span all storage layers or just Postgres?
3. Are there background jobs to clean orphaned entries?
4. How are deletion failures handled and retried?
5. Is there audit logging for deletion operations?

## Testing Strategy

### Unit Tests:
1. Test delete removes from all expected components
2. Verify orphaned entry detection works
3. Test deletion failure handling and rollback

### Integration Tests:
1. End-to-end deletion across all storage layers
2. Verify vector search doesn't return deleted memory
3. Test cache invalidation after deletion

### Consistency Tests:
1. Simulate partial failures during deletion
2. Verify reconciliation processes work
3. Test concurrent deletions don't cause orphaned entries

## Constraints
- All work stays within: `core/memory/`, `services/memory/`, `persistence/`, `storage/`, `tests/core/memory/`, `tests/persistence/`
- DO NOT modify `chat_runtime.py` during this sprint
- No edits - only discovery and reporting
- Focus on finding orphaned-index risks, not fixing them

## Success Criteria
- Complete mapping of all deletion paths
- Identified orphaned-index risks with severity ratings
- Analysis of current deletion implementation
- Proposed delete gate contract
- Gap prioritization for fixing deletion semantics