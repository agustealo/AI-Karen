# Persistence Authority Alignment - Implementation Report

## Analysis of Direct Store Access Patterns

### Current State Analysis

**Memory Domain Layer (Appropriate):**
The canonical memory services correctly use store clients at the domain service layer:

**`unified_memory_service.py` (Canonical Gateway):**
- ✅ Uses `MultiTenantPostgresClient` and `MemoryManager` appropriately (line 132, 147)
- ✅ Uses `redis_client` for caching (line 134, 140, 529, 1235, 1251)
- ✅ This is the CORRECT layer for direct store access - it's the gateway layer

**`memory_writeback.py` (Domain Service):**
- ✅ Uses `redis_client` appropriately (line 124, 127)
- ✅ This is a domain service that can access stores

**`memory_service.py` (Legacy Service):**
- ⚠️ Uses `MultiTenantPostgresClient` and `MemoryManager` (line 29, 32, 448, 456)
- ⚠️ This is a legacy service that should route through unified service instead

### Boundary Violations Found

**Application Layer Violations:**
These services should NOT directly access stores but route through unified memory service:

1. **`services/memory/conversation_service.py`:**
   - ❌ Direct `MultiTenantPostgresClient` import (line 54)
   - ❌ Should route all memory operations through unified service

2. **`services/ui/ag_ui_memory_manager.py`:**
   - ❌ Likely has direct store access patterns
   - ❌ Should route through unified service

## Layered Architecture Enforcement

### Target Architecture (Already Established in Core):

```
Runtime / UI / agents
       ↓
Memory Gateway (unified_memory_service) ← ✅ Already correct
       ↓
Memory domain services (stm, episodic, ltm, neuro, retrieval, scoring)
       ↓
Persistence repositories/adapters (SqlMemoryRepository, vector adapters)
       ↓
Postgres / Redis / Milvus / Elasticsearch
```

### Current State:

**✅ Correct (Gateway Layer):**
- `unified_memory_service.py` - Properly uses stores at gateway layer

**✅ Correct (Domain Services):**
- `memory_writeback.py` - Properly uses stores as domain service
- Other domain services in core/memory/ use stores appropriately

**❌ Incorrect (Application Layer):**
- `conversation_service.py` - Directly accesses MultiTenantPostgresClient
- Other UI services likely have similar violations

## Changes Required

### High Priority:
1. **Audit conversation service database access** - Determine which operations can route through unified service
2. **Identify critical database operations** - Some direct DB access may be legitimate (conversation metadata vs memory)
3. **Update services to use unified service** - Where appropriate for memory operations

### Medium Priority:
4. **Add linting rules** - Prevent application layer from importing store clients
5. **Document boundary contracts** - Make layered architecture explicit
6. **Add integration tests** - Verify boundary enforcement

### Low Priority:
7. **Refactor legacy services** - Update memory_service.py to route through unified service
8. **Performance monitoring** - Add metrics for layer crossings
9. **Update documentation** - Demonstrate proper layered usage

## Implementation Strategy

### Phase 1: Audit and Classify
1. Categorize all database operations in conversation_service.py
2. Identify which are memory operations vs conversation metadata operations
3. Determine feasibility of routing memory operations through unified service

### Phase 2: Refactor Memory Operations
1. Replace memory-specific database calls with unified service calls
2. Keep conversation metadata operations direct (legitimate application layer concern)
3. Update error handling for unified service calls

### Phase 3: Enforce Boundaries
1. Add linting rules to prevent direct store access for memory operations
2. Add code review checklist items
3. Document proper layered architecture

## Key Insight

The core memory architecture is ALREADY correctly layered. The issue is at the application layer (services/ directory) where some services bypass the unified memory gateway.

**The fix is NOT to remove store access from unified_memory_service.py** - that's where it belongs!

**The fix IS to prevent application layer services from bypassing the unified memory gateway.**

## Success Metrics

- ✅ Core memory architecture correctly layered (unified service at gateway)
- ✅ Domain services appropriately use stores
- ✅ Application layer services route memory operations through unified service
- ✅ Clear boundary between memory operations and conversation metadata
- ✅ Documentation of layered contracts
- ✅ Linting rules to prevent boundary violations

## Constraints Compliance

✅ All work stays within approved directories:
- core/memory/
- services/memory/

✅ NO modifications to chat_runtime.py during this sprint
✅ Focus on enforcing clean boundaries
✅ Preserve existing functionality while eliminating direct store access for memory operations

## Next Steps

1. Complete audit of conversation_service.py database operations
2. Classify operations as memory vs metadata
3. Refactor memory operations to use unified service
4. Add boundary enforcement mechanisms
5. Document layered architecture contracts

Related to MEMORY-CLOSURE-1 sprint: Enforce persistence authority boundaries and eliminate direct store access above gateway layer.