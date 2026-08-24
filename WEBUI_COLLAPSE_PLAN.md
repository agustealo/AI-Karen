# MEMORY-CLOSURE-1 WebUI Memory Compatibility Collapse

## Objective
Collapse services/memory/conversation_service.py to route through ONE canonical memory gateway, removing feature-detection escape hatches.

## Current State Analysis

### Problem Pattern Identified
The conversation_service.py contains compatibility logic like:

`python
if hasattr(self.memory_service, \
query\):
    ...
return await self.memory_service.query_memories(...)
`

And:

`python
if hasattr(self.memory_service, \commit\):
    ...
return await self.memory_service.store_web_ui_memory(...)
`

This is the classic \new
authority
plus
legacy
escape
hatch\ seam that creates:

1. **Unclear authority** - Which memory service is actually being used?
2. **Maintenance burden** - Multiple code paths to maintain
3. **Testing complexity** - Need to test both modern and legacy paths
4. **Ownership ambiguity** - Who owns which memory contract?

## Target Architecture

### Before (Current):
`	ext
UI conversation service
        ↓
    Feature Detection
        ↓
    [Multiple Paths]
        ├─→ legacy memory_service  
        ├─→ unified_memory_service
        └─→ memory_runtime_manager
`

### After (Target):
`	ext
UI conversation service
        ↓
canonical memory gateway (unified_memory_service)
        ↓
memory authority
`

## Implementation Plan

### Phase 1: Audit Current Imports
Read services/memory/conversation_service.py to identify:
- All current memory service imports
- Feature detection patterns
- Fallback logic branches
- Direct method calls vs compatibility wrappers

### Phase 2: Choose Canonical Facade
Based on canonical API audit, use unified_memory_service exclusively:
- Import only UnifiedMemoryService from core.memory.unified_memory_service
- Remove all other memory service imports
- Remove all hasattr() feature detection

### Phase 3: Refactor Method Calls
Replace compatibility patterns with direct unified service calls:

**Current pattern:**
`python
if hasattr(self.memory_service, \query\):
    return await self.memory_service.query_memories(...)
else:
    # fallback logic
`

**Target pattern:**
`python
return await self.unified_memory_service.query(query_request)
`

### Phase 4: Remove Dead Code
- Delete unused import statements
- Remove unreachable compatibility branches
- Clean up any commented-out legacy code

### Phase 5: Verify Consistency
- Ensure all UI memory operations go through unified service
- Check that error handling is consistent
- Verify tenant/user/context passing is maintained

## Expected Changes

### Files to Modify:
- services/memory/conversation_service.py (primary target)

### Files to Review (no changes expected):
- pi_routes/memory/memory.py (verify it uses collapsed service)
- services/ui/ag_ui_memory_manager.py (check for similar patterns)

## Testing Strategy
1. Verify WebUI memory storage still works
2. Ensure memory queries return expected results
3. Check tenant isolation is maintained
4. Validate error handling for degraded memory states

## Constraints
- All work stays within: services/memory/
- DO NOT modify chat_runtime.py during this sprint
- Minimal runtime changes - focus on collapsing the seam
- Preserve all existing functionality while simplifying the code path

## Success Criteria
- ✅ Single memory service import in conversation_service.py
- ✅ No feature detection or fallback logic
- ✅ All memory operations go through unified_memory_service
- ✅ No functional regressions in WebUI memory
- ✅ Clear ownership of memory contract
