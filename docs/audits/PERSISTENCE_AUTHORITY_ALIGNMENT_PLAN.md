# MEMORY-CLOSURE-1 Persistence Authority Alignment

## Objective
Enforce a clean boundary: Runtime/UI/agents → Memory Gateway → Memory domain services → Persistence repositories/adapters → stores. Ensure no caller above the gateway knows which backing store owns what.

## Target Architecture

### Clean Layered Boundary:

`
Runtime / UI / agents
       ↓
Memory Gateway (unified_memory_service)
       ↓
Memory domain services (stm, episodic, ltm, neuro, retrieval, scoring)
       ↓
Persistence repositories/adapters (SqlMemoryRepository, vector adapters)
       ↓
Postgres / Redis / Milvus / Elasticsearch
`

### Key Principle:
**No caller above the gateway should know which backing store owns what.**

## Current State Problems

### Direct Store Access Patterns:

**1. Direct Redis Access:**
- core/memory/memory_writeback.py:124 - Redis client passed directly to writeback system
- This bypasses the gateway and creates direct dependency on Redis

**2. Direct Database Manager:**
- Various services import MemoryManager directly from database/memory_manager.py
- Bypasses the unified memory service gateway

**3. Direct Vector Store Calls:**
- Potential direct Milvus/Elasticsearch access in retrieval layers
- Should route through unified service instead

### Import Analysis Needed:

**From Application Layer (Runtime/UI/agents):**
- Find direct imports of persistence classes
- Identify direct database client usage
- Locate direct vector store calls

**From Gateway Layer:**
- Verify unified_memory_service only imports domain services
- Check for any direct persistence imports in the gateway
- Ensure gateway doesn't know about specific stores

**From Domain Services:**
- Verify domain services only use repositories/adapters
- Check for direct store access in domain logic
- Ensure proper abstraction boundaries

## Boundary Enforcement Strategy

### Layer 1: Application Layer (Runtime/UI/agents)
**Allowed Imports:**
- i_karen_engine.core.memory.unified_memory_service ✓
- i_karen_engine.core.memory.runtime_gateway ✓ (for availability checks)

**Forbidden Imports:**
- i_karen_engine.database.memory_manager ✗
- i_karen_engine.database.client ✗
- Direct Redis/Milvus/Elasticsearch clients ✗
- i_karen_engine.persistence.repositories ✗

**Enforcement:**
- Add linting rules to prevent forbidden imports
- Code review checklist for boundary violations
- Static analysis to detect direct persistence access

### Layer 2: Gateway Layer (unified_memory_service)
**Allowed Imports:**
- Domain services (stm, episodic, ltm, 
euro, etrieval, scoring)
- Memory policy and configuration
- Service registry for resolution

**Forbidden Imports:**
- Direct database clients ✗
- Specific store implementations ✗
- Repository implementations ✗

**Responsibility:**
- Route requests to appropriate domain services
- Handle cross-domain coordination
- Provide unified API contract
- Manage fallback and degradation

### Layer 3: Domain Services (stm, episodic, ltm, neuro, retrieval, scoring)
**Allowed Imports:**
- Repository interfaces and adapters
- Memory models and policy
- Internal domain utilities

**Forbidden Imports:**
- Direct store clients ✗ (unless adapter implementation)
- Other domain services (use coordination layer) ✗

**Responsibility:**
- Implement domain-specific memory logic
- Coordinate with repositories for persistence
- Handle domain-specific validation and transformations

### Layer 4: Repository/Adapter Layer
**Allowed Imports:**
- Store clients (Redis, Milvus, Elasticsearch, Postgres)
- Database models and schemas
- Store-specific configuration

**Responsibility:**
- Implement persistence operations
- Handle store-specific optimizations
- Translate between domain models and store models
- Manage store connections and lifecycle

## Specific Refactoring Tasks

### High Priority:
1. **Audit direct imports** - Find all forbidden import patterns
2. **Refactor memory_writeback.py** - Remove direct Redis client passing
3. **Update services using MemoryManager** - Route through unified service instead
4. **Check retrieval layer** - Ensure vector operations go through domain services

### Medium Priority:
5. **Add linting rules** - Prevent boundary violations
6. **Update documentation** - Make layered contract explicit
7. **Add integration tests** - Verify boundary enforcement
8. **Review error handling** - Ensure proper error propagation across layers

### Low Priority:
9. **Performance monitoring** - Add metrics for layer crossings
10. **Dependency analysis** - Visualize current dependency graph
11. **Refactor legacy paths** - Remove any remaining direct access patterns
12. **Update examples and tutorials** - Demonstrate proper layered usage

## Implementation Examples

### Before (Direct Store Access):
`python
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.memory_manager import MemoryManager

class SomeService:
    def __init__(self):
        self.db_client = MultiTenantPostgresClient()
        self.memory_manager = MemoryManager(self.db_client)
    
    async def store_memory(self, data):
        await self.memory_manager.store_memory(data)  # Direct access
`

### After (Through Gateway):
`python
from ai_karen_engine.core.memory.unified_memory_service import UnifiedMemoryService

class SomeService:
    def __init__(self, memory_service: UnifiedMemoryService):
        self.memory_service = memory_service
    
    async def store_memory(self, data):
        request = MemoryCommitRequest(**data)
        await self.memory_service.commit(request)  # Through gateway
`

## Documentation Requirements

### Layered Contract Documentation:

**Layer 1 - Application Contract:**
- Public API of unified_memory_service
- Request/response models
- Error handling semantics
- Availability and degradation behavior

**Layer 2 - Gateway Contract:**
- Domain service interfaces
- Coordination patterns
- Fallback and routing logic
- Performance characteristics

**Layer 3 - Domain Service Contract:**
- Repository interfaces
- Domain model transformations
- Validation and business rules
- Inter-domain communication patterns

**Layer 4 - Repository Contract:**
- Store adapter interfaces
- Store-specific operations
- Error mapping and translation
- Performance optimization hints

## Testing Strategy

### Contract Tests:
1. Test gateway layer doesn't depend on specific stores
2. Verify domain services use repositories correctly
3. Ensure application layer only uses gateway APIs

### Integration Tests:
1. End-to-end flows through all layers
2. Verify error propagation across boundaries
3. Test fallback and degradation behavior

### Boundary Tests:
1. Attempt forbidden imports (should fail linting)
2. Try to access stores directly (should fail at runtime)
3. Verify proper layer separation in all scenarios

## Constraints
- All work stays within: core/memory/, services/memory/, persistence/, storage/, 	ests/core/memory/, 	ests/persistence/
- DO NOT modify chat_runtime.py during this sprint
- Focus on enforcing clean boundaries
- Document the layered contract explicitly

## Success Criteria
- Complete audit of direct store access patterns
- Refactored memory_writeback.py to remove direct Redis access
- Updated services to use unified memory service instead of MemoryManager
- Added linting rules to prevent boundary violations
- Comprehensive documentation of layered contract
- Integration tests verifying boundary enforcement
- No caller above gateway knows which backing store owns what
