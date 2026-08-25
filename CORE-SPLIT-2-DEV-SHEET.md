# CORE-SPLIT-2 Implementation Sprint

**Phase**: Architecture Refactoring - Core/Platform/Runtime Separation + Cognitive Memory Lifecycle
**Priority**: High - Foundational reorganization
**Completion Gate**: All 18 technical criteria + 19 cognitive behavior criteria must pass

## Prerequisites

```text
[ ] Architecture tests exist and enforce CORE ↛ PLATFORM/Provider/Extension
[ ] All xfails have owner, migration sprint, sunset condition, and expiry
[ ] Development branch created from main
[ ] CI pipeline updated with new architecture test rules
[ ] Documentation updated with new layer definitions
[ ] Cognitive Continuity Invariant added to ARCHITECTURE.md
[ ] Memory cognitive architecture designed: lifecycle, types, associative recall, forgetting
[ ] Cognitive proof suite test plan approved
```

## Phase 1: Foundation & Safety (Do First)

### 1.1 Architecture Test Enforcement
**Owner**: Architecture Team
**Risk**: Low - Read-only operations
**Blocking**: Yes - Must complete before Phase 2

```text
[ ] Add test rule: core ↛ platform (hard fail)
[ ] Add test rule: core ↛ providers (hard fail)
[ ] Add test rule: core ↛ extensions (hard fail)
[ ] Update xfails: Add owner, sprint, sunset, expiry to all
[ ] Set xfail expiry maximum: 2 sprints
[ ] Run full architecture test suite
[ ] Document all violations found
```

**Files**: `tests/architecture/`
**Commands**: `pytest tests/architecture/`

### 1.2 Dependency Audit
**Owner**: Core Team
**Risk**: Low - Read-only operations
**Blocking**: Yes - Must complete before Phase 2

```text
[ ] Audit core/memory/ imports
[ ] Audit core/agent_client/ imports
[ ] Audit core/personalization/ imports
[ ] Audit core/reasoning/retrieval/ imports
[ ] Document all violations found
[ ] Classify each violation by severity
[ ] Create migration priority list
```

**Output**: `docs/CORE-SPLIT-2-dependency-audit.md`

### 1.3 Create Migration Branch Structure
**Owner**: Dev Team
**Risk**: Low - Branch setup only
**Blocking**: Yes - Required for subsequent work

```text
[ ] Create feature branch: refactor/core-split-2
[ ] Set up branch protection rules
[ ] Create worktree for isolated testing
[ ] Create staging environment
[ ] Set up rollback procedures
```

---

## Phase 2: Memory Decontamination + Cognitive Architecture (Critical Path)

### 2.1 Define Cognitive Memory Contracts and Lifecycle
**Owner**: Memory Team + Cognitive Architecture Team
**Risk**: Medium - Interface design
**Blocking**: No - Can proceed in parallel with 2.2
**Estimated Time**: 3-4 days

```text
[ ] Create core/memory/contracts.py
    [ ] Define MemoryService interface
    [ ] Define RetrievalPort interface
    [ ] Define ConsolidationPort interface
    [ ] Define RecallPort interface
    [ ] Define EmbeddingPort interface
    [ ] Remove all platform-specific types

[ ] Create core/memory/policy.py
    [ ] Define MemoryWorthinessPolicy
    [ ] Define ConsolidationPolicy
    [ ] Define RetrievalPolicy
    [ ] Define ContextBudgetPolicy
    [ ] Define ForgettingPolicy (decay, suppression, consolidation triggers)
    [ ] Define SalienceScoringPolicy (novelty, surprise, emphasis, goal relevance)

[ ] Create core/memory/lifecycle/
    [ ] Define MemoryLifecycle enum: PERCEIVE → ENCODE → SCORE_SALIENCE → ASSOCIATE → STORE_EPISODE → REPLAY_REFLECT → CONSOLIDATE → GENERALIZE → RETRIEVE → RECONSOLIDATE → DECAY_SUPERSEDE_FORGET
    [ ] Extract memory lifecycle hooks
    [ ] Define state transitions
    [ ] Extract cleanup policies
    [ ] Define reconsolidation protocol (revise interpretation, preserve provenance)

[ ] Create core/memory/claims/
    [ ] Define MemoryClaim model: subject, predicate, object, confidence, provenance, evidence, asserted_at, valid_from, valid_until, last_confirmed, contradiction_refs, supersedes, status
    [ ] Define ClaimStatus enum: OBSERVED, INFERRED, USER_ASSERTED, VERIFIED, DISPUTED, SUPERSEDED, STALE, RETRACTED
    [ ] Implement contradiction detection and lowering confidence

[ ] Create core/memory/types/ (12 memory systems)
    [ ] WorkingMemory: current mental workspace
    [ ] EpisodicMemory: specific interactions and experiences
    [ ] SemanticMemory: durable facts and generalized knowledge
    [ ] AutobiographicalMemory: Karen-user history and meaningful shared events
    [ ] PreferenceMemory: likes, dislikes, styles, recurring choices
    [ ] ProceduralMemory: successful ways of doing things
    [ ] ProspectiveMemory: intentions, commitments, unfinished work
    [ ] RelationalMemory: people, projects, objects and how they connect
    [ ] TemporalMemory: when something was true and for how long
    [ ] SalienceMemory: importance, surprise, emotional relevance, consequences
    [ ] BeliefMemory: claims with confidence and evidence
    [ ] MetaMemory: what Karen knows, doubts, forgot, or needs to verify

[ ] Create core/memory/scoring/
    [ ] Extract recall scoring logic
    [ ] Extract relevance scoring
    [ ] Extract temporal decay
    [ ] Extract salience scoring (novelty, surprise, user emphasis, goal relevance, consequence, repetition)
    [ ] Remove UI-specific scoring

[ ] Create core/memory/retrieval/
    [ ] Extract retrieval strategies
    [ ] Extract fusion logic
    [ ] Extract reranking logic
    [ ] Remove vector-store implementations

[ ] Create core/memory/consolidation/
    [ ] Extract consolidation logic
    [ ] Extract memory merging
    [ ] Extract conflict resolution
    [ ] Extract forgetting logic (decay, suppression, consolidation-based compression)
```

**Files**:
- `src/ai_karen_engine/core/memory/contracts.py` (new)
- `src/ai_karen_engine/core/memory/policy.py` (new)
- `src/ai_karen_engine/core/memory/lifecycle/` (new)
- `src/ai_karen_engine/core/memory/claims/` (new)
- `src/ai_karen_engine/core/memory/types/` (new)
- `src/ai_karen_engine/core/memory/scoring/` (new)
- `src/ai_karen_engine/core/memory/retrieval/` (new)
- `src/ai_karen_engine/core/memory/consolidation/` (new)

**Tests**: `tests/core/memory/test_*.py`
- `test_lifecycle.py`
- `test_claims.py`
- `test_salience.py`
- `test_forgetting.py`
- `test_consolidation.py`

### 2.2 Remove Platform Dependencies from Core Memory
**Owner**: Memory Team
**Risk**: High - Breaking changes
**Blocking**: Yes - Depends on 2.1
**Estimated Time**: 3-4 days

```text
[ ] Identify all WebUI-specific types in core/memory/
    [ ] UISource, WEB, DESKTOP, API, AG_UI types
    [ ] Document replacement strategy

[ ] Replace SQLAlchemy usage with port interfaces
    [ ] Replace direct queries with RetrievalPort calls
    [ ] Replace database models with contracts
    [ ] Remove Postgres client imports

[ ] Extract embedding implementation
    [ ] Move EmbeddingManager to runtime/
    [ ] Create EmbeddingPort interface
    [ ] Update all embedding usage

[ ] Update core/memory/memory_service.py
    [ ] Remove all UI-specific code
    [ ] Replace with contract-based interfaces
    [ ] Add deprecation notice for old API
    [ ] Create adapter layer for backward compatibility

[ ] Create core/memory/self_model/
    [ ] Define SelfModel: identity, stable principles, capabilities, capability limits, role relationships, learned strategies, current commitments, active goals, confidence, history of significant decisions
    [ ] Separate from UserModel and RelationshipModel
    [ ] Ensure SelfModel is governed and does not pretend consciousness

[ ] Create core/memory/user_model/
    [ ] Define UserModel: explicit preferences, inferred preferences, communication patterns, projects, goals, relationships, routines, skills, decisions, evolving beliefs
    [ ] Implement evidence-backed updates (no one-event canon)

[ ] Create core/memory/relationship_model/
    [ ] Define RelationshipModel: Karen↔User shared projects, past decisions, interaction style, trust-relevant facts, unresolved threads, interaction history
    [ ] Ensure cross-tenant isolation

[ ] Create core/memory/prospective/
    [ ] Define ProspectiveMemory: intention, trigger, status, priority, created_from
    [ ] Implement trigger-based resurfacing
    [ ] Distinguish from scheduler infrastructure (cron = PLATFORM)

[ ] Create core/memory/reflection/
    [ ] Define ReflectionEngine: derives knowledge from experience
    [ ] Implement evidence checking before promotion
    [ ] Implement promotion/defer/reject gates
    [ ] Ensure one isolated event does not become strong user preference

[ ] Create core/memory/associative/
    [ ] Implement spreading activation graph
    [ ] Define RecallScore = semantic_similarity + associative_activation + temporal_relevance + salience + relationship_relevance + current_goal_relevance + repetition_strength + causal_relevance + unresolved_intention_relevance + explicit_user_priority - contradiction_penalty - staleness - interference
    [ ] Implement activation spreading from recalled concepts to neighbors
    [ ] Ensure reasoning retrieval consumes RecallPort, does not own storage

[ ] Update imports across codebase
    [ ] Update all callers to use new interfaces
    [ ] Update type annotations
    [ ] Update documentation
```

**Files**:
- `src/ai_karen_engine/core/memory/memory_service.py` (refactor)
- `src/ai_karen_engine/runtime/memory/coordinator.py` (new)
- `src/ai_karen_engine/runtime/memory/context_adapter.py` (new)

### 2.3 Create Platform Memory Implementations
**Owner**: Platform Team
**Risk**: Medium - New implementations
**Blocking**: No - Can proceed in parallel with 2.2
**Estimated Time**: 4-5 days

```text
[ ] Create platform/memory/ structure
    [ ] postgres/
    [ ] redis/
    [ ] milvus/
    [ ] elasticsearch/
    [ ] kuzu/
    [ ] duckdb/

[ ] Create platform/memory/postgres/
    [ ] Implement RetrievalPort for Postgres
    [ ] Implement EmbeddingPort for Postgres
    [ ] Implement ConsolidationPort for Postgres
    [ ] Implement MemoryClaim persistence with temporal validity
    [ ] Implement contradiction/supersession tracking
    [ ] Add health checks
    [ ] Add connection pooling

[ ] Create platform/memory/redis/
    [ ] Implement caching layer
    [ ] Implement session management
    [ ] Implement prospective memory trigger store
    [ ] Add health checks

[ ] Create platform/memory/milvus/
    [ ] Implement vector search
    [ ] Implement RetrievalPort for vector stores
    [ ] Add health checks

[ ] Create platform/memory/elasticsearch/
    [ ] Implement text search
    [ ] Implement RetrievalPort for text stores
    [ ] Add health checks

[ ] Create platform/memory/kuzu/
    [ ] Implement graph retrieval for associative memory
    [ ] Implement RetrievalPort for graph stores
    [ ] Add health checks

[ ] Create platform/memory/duckdb/
    [ ] Implement analytics queries
    [ ] Implement RetrievalPort for analytics
    [ ] Add health checks
```

**Files**:
- `src/ai_karen_engine/platform/memory/postgres/` (new)
- `src/ai_karen_engine/platform/memory/redis/` (new)
- `src/ai_karen_engine/platform/memory/milvus/` (new)
- `src/ai_karen_engine/platform/memory/elasticsearch/` (new)
- `src/ai_karen_engine/platform/memory/kuzu/` (new)
- `src/ai_karen_engine/platform/memory/duckdb/` (new)

### 2.4 Move UI-Specific Memory Models
**Owner**: UI Team
**Risk**: Low - Moving existing code
**Blocking**: Yes - Depends on 2.2
**Estimated Time**: 1-2 days

```text
[ ] Create interfaces/ui/memory_models.py
    [ ] Move WebUIMemoryService
    [ ] Move UI-specific DTOs
    [ ] Move UI-specific types

[ ] Update UI imports
    [ ] Update all UI code to use new location
    [ ] Update type annotations
    [ ] Update documentation

[ ] Deprecate old paths
    [ ] Add deprecation warnings
    [ ] Document migration path
    [ ] Set removal deadline (2 sprints)
```

**Files**:
- `src/ai_karen_engine/interfaces/ui/memory_models.py` (new)

### 2.5 Cognitive Proof Suite
**Owner**: Cognitive Architecture Team + QA
**Risk**: Medium - New test requirements
**Blocking**: Yes - Required before completion gate
**Estimated Time**: 3-4 days

```text
[ ] Create tests/cognitive/test_memory_lifecycle.py
    [ ] Verify perceive → encode → score → associate → store → replay → consolidate → generalize → retrieve → reconsolidate → decay flow
    [ ] Verify reconsolidation revises interpretation while preserving provenance
    [ ] Verify memory states transition correctly

[ ] Create tests/cognitive/test_memory_types.py
    [ ] Verify all 12 memory types are represented
    [ ] Verify WorkingMemory is bounded and transient
    [ ] Verify EpisodicMemory stores specific interactions
    [ ] Verify SemanticMemory stores generalized knowledge
    [ ] Verify AutobiographicalMemory tracks Karen-user history
    [ ] Verify PreferenceMemory tracks likes/dislikes/styles
    [ ] Verify ProceduralMemory tracks successful patterns
    [ ] Verify ProspectiveMemory tracks intentions/commitments
    [ ] Verify RelationalMemory tracks connections
    [ ] Verify TemporalMemory tracks validity periods
    [ ] Verify SalienceMemory tracks importance/surprise
    [ ] Verify BeliefMemory tracks claims with confidence
    [ ] Verify MetaMemory tracks what Karen knows/doubts/forgot

[ ] Create tests/cognitive/test_associative_recall.py
    [ ] Verify recall uses spreading activation, not just vector similarity
    [ ] Verify activation spreads to graph neighbors
    [ ] Verify Porsche Cayenne example: discussing "starter" activates battery, fuse, hatch, etc.
    [ ] Verify RecallScore formula components are weighted correctly
    [ ] Verify cross-tenant memories cannot activate

[ ] Create tests/cognitive/test_controlled_forgetting.py
    [ ] Verify low-value unused memories decay in retrieval rank
    [ ] Verify irrelevant memories lose activation in current context (suppression)
    [ ] Verify repeated episodes consolidate into semantic memory
    [ ] Verify one isolated event does not become strong preference
    [ ] Verify deleted/retracted memories cannot reappear from indexes

[ ] Create tests/cognitive/test_uncertainty_contradiction.py
    [ ] Verify MemoryClaim includes confidence, provenance, evidence, temporal validity
    [ ] Verify contradictory memories lower confidence
    [ ] Verify newer preference supersedes older preference
    [ ] Verify old episode remains available as provenance
    [ ] Verify CORTEX cannot treat inferred memory as verified fact

[ ] Create tests/cognitive/test_self_user_relationship.py
    [ ] Verify SelfModel exists and is governed
    [ ] Verify UserModel is evidence-backed (no one-event canon)
    [ ] Verify RelationshipModel tracks shared projects and unresolved threads
    [ ] Verify cross-tenant isolation in all models

[ ] Create tests/cognitive/test_prospective_memory.py
    [ ] Verify ProspectiveMemory tracks intentions and commitments
    [ ] Verify trigger-based resurfacing works
    [ ] Verify ProspectiveMemory is CORE, scheduler is PLATFORM

[ ] Create tests/cognitive/test_reflection.py
    [ ] Verify ReflectionEngine derives knowledge from experience
    [ ] Verify evidence checking before promotion
    [ ] Verify promotion/defer/reject gates
    [ ] Verify 8 rejections of unified diffs promotes preference for complete files

[ ] Create tests/cognitive/test_memory_cortex_coupling.py
    [ ] Verify retrieved memories influence CORTEX action selection
    [ ] Verify memory feeds CORTEX decisions, not just prompt text
    [ ] Verify CORTEX sees preference + project-state memory and chooses accordingly

[ ] Create tests/cognitive/test_provenance_temporal.py
    [ ] Verify event time is distinct from conversation time
    [ ] Verify temporal validity ranges are respected
    [ ] Verify memory reconstruction preserves provenance
    [ ] Verify provider replacement does not change memory semantics

[ ] Create tests/cognitive/test_resilience.py
    [ ] Verify Redis/Milvus outage degrades honestly rather than inventing recall
    [ ] Verify missing backend does not fabricate memories
    [ ] Verify health checks are evidence-backed
```

**Files**:
- `tests/cognitive/test_memory_lifecycle.py` (new)
- `tests/cognitive/test_memory_types.py` (new)
- `tests/cognitive/test_associative_recall.py` (new)
- `tests/cognitive/test_controlled_forgetting.py` (new)
- `tests/cognitive/test_uncertainty_contradiction.py` (new)
- `tests/cognitive/test_self_user_relationship.py` (new)
- `tests/cognitive/test_prospective_memory.py` (new)
- `tests/cognitive/test_reflection.py` (new)
- `tests/cognitive/test_memory_cortex_coupling.py` (new)
- `tests/cognitive/test_provenance_temporal.py` (new)
- `tests/cognitive/test_resilience.py` (new)

### 2.3 Create Platform Memory Implementations
**Owner**: Platform Team
**Risk**: Medium - New implementations
**Blocking**: No - Can proceed in parallel with 2.2
**Estimated Time**: 4-5 days

```text
[ ] Create platform/memory/ structure
    [ ] postgres/
    [ ] redis/
    [ ] milvus/
    [ ] elasticsearch/
    [ ] kuzu/
    [ ] duckdb/

[ ] Create platform/memory/postgres/
    [ ] Implement RetrievalPort for Postgres
    [ ] Implement EmbeddingPort for Postgres
    [ ] Implement ConsolidationPort for Postgres
    [ ] Add health checks
    [ ] Add connection pooling

[ ] Create platform/memory/redis/
    [ ] Implement caching layer
    [ ] Implement session management
    [ ] Add health checks

[ ] Create platform/memory/milvus/
    [ ] Implement vector search
    [ ] Implement RetrievalPort for vector stores
    [ ] Add health checks

[ ] Create platform/memory/elasticsearch/
    [ ] Implement text search
    [ ] Implement RetrievalPort for text stores
    [ ] Add health checks

[ ] Create platform/memory/kuzu/
    [ ] Implement graph retrieval
    [ ] Implement RetrievalPort for graph stores
    [ ] Add health checks

[ ] Create platform/memory/duckdb/
    [ ] Implement analytics queries
    [ ] Implement RetrievalPort for analytics
    [ ] Add health checks
```

**Files**:
- `src/ai_karen_engine/platform/memory/postgres/` (new)
- `src/ai_karen_engine/platform/memory/redis/` (new)
- `src/ai_karen_engine/platform/memory/milvus/` (new)
- `src/ai_karen_engine/platform/memory/elasticsearch/` (new)
- `src/ai_karen_engine/platform/memory/kuzu/` (new)
- `src/ai_karen_engine/platform/memory/duckdb/` (new)

### 2.4 Move UI-Specific Memory Models
**Owner**: UI Team
**Risk**: Low - Moving existing code
**Blocking**: Yes - Depends on 2.2
**Estimated Time**: 1-2 days

```text
[ ] Create interfaces/ui/memory_models.py
    [ ] Move WebUIMemoryService
    [ ] Move UI-specific DTOs
    [ ] Move UI-specific types

[ ] Update UI imports
    [ ] Update all UI code to use new location
    [ ] Update type annotations
    [ ] Update documentation

[ ] Deprecate old paths
    [ ] Add deprecation warnings
    [ ] Document migration path
    [ ] Set removal deadline (2 sprints)
```

**Files**:
- `src/ai_karen_engine/interfaces/ui/memory_models.py` (new)

---

## Phase 3: Agent-Client Retirement (Critical Path)

### 3.1 Audit Agent-Client Dependencies
**Owner**: Core Team
**Risk**: Low - Read-only operations
**Blocking**: No - Can proceed immediately
**Estimated Time**: 1 day

```text
[ ] Document all tool execution in core/agent_client/
    [ ] PythonInterpreter usage
    [ ] DockerInterpreter usage
    [ ] SubprocessInterpreter usage
    [ ] IPythonInterpreter usage
    [ ] SearchTool usage
    [ ] DocumentsTool usage

[ ] Document all direct method calls
    [ ] execute_code() callers
    [ ] search_web() callers
    [ ] process_document() callers

[ ] Document recall coupling
    [ ] Direct recall imports
    [ ] Recall state management
    [ ] Recall dependency patterns

[ ] Classify each usage as:
    [ ] Genuine core recall logic (keep)
    [ ] Tool execution (move to extensions)
    [ ] Legacy orchestration (remove)
    [ ] Runtime capability (move to runtime)
```

**Output**: `docs/CORE-SPLIT-2-agent-client-audit.md`

### 3.2 Extract Genuine Core Recall Logic
**Owner**: Memory Team
**Risk**: Medium - Logic extraction
**Blocking**: No - Can proceed in parallel with 3.1
**Estimated Time**: 2-3 days

```text
[ ] Identify recall-specific logic in agent_client
    [ ] Recall strategy selection
    [ ] Memory eligibility determination
    [ ] Context-aware recall triggers

[ ] Create core/recall/contracts.py
    [ ] Define RecallStrategy interface
    [ ] Define RecallTrigger interface
    [ ] Define RecallEligibility interface

[ ] Create core/recall/strategy.py
    [ ] Extract recall strategy logic
    [ ] Extract eligibility logic
    [ ] Extract trigger logic

[ ] Update other core modules
    [ ] Import from core/recall instead of agent_client
    [ ] Update type annotations
    [ ] Update tests
```

**Files**:
- `src/ai_karen_engine/core/recall/contracts.py` (new)
- `src/ai_karen_engine/core/recall/strategy.py` (new)

### 3.3 Create Extension Capability Interfaces
**Owner**: Extensions Team
**Risk**: Medium - Interface design
**Blocking**: Yes - Required before removing agent_client
**Estimated Time**: 3-4 days

```text
[ ] Create extensions/contracts.py
    [ ] Define Capability interface
    [ ] Define ToolCapability interface
    [ ] Define ExecutionResult interface
    [ ] Define CapabilityManifest interface

[ ] Create extensions/python/
    [ ] Implement PythonExecutionCapability
    [ ] Add IPython support
    [ ] Add safety constraints
    [ ] Add resource limits

[ ] Create extensions/docker/
    [ ] Implement DockerExecutionCapability
    [ ] Add container isolation
    [ ] Add resource limits
    [ ] Add security policies

[ ] Create extensions/subprocess/
    [ ] Implement SubprocessCapability
    [ ] Add timeout handling
    [ ] Add output capture
    [ ] Add safety checks

[ ] Create extensions/search/
    [ ] Implement WebSearchCapability
    [ ] Add result ranking
    [ ] Add source validation
    [ ] Add caching

[ ] Create extensions/documents/
    [ ] Implement DocumentProcessingCapability
    [ ] Add format support (PDF, DOCX, etc.)
    [ ] Add text extraction
    [ ] Add metadata extraction

[ ] Create extensions/manifest.py
    [ ] Define extension manifest structure
    [ ] Add capability declarations
    [ ] Add version support
    [ ] Add deprecation support
```

**Files**:
- `src/ai_karen_engine/extensions/contracts.py` (new)
- `src/ai_karen_engine/extensions/python/` (new)
- `src/ai_karen_engine/extensions/docker/` (new)
- `src/ai_karen_engine/extensions/subprocess/` (new)
- `src/ai_karen_engine/extensions/search/` (new)
- `src/ai_karen_engine/extensions/documents/` (new)
- `src/ai_karen_engine/extensions/manifest.py` (new)

### 3.4 Create Runtime Capability Coordination
**Owner**: Runtime Team
**Risk**: Medium - New coordination layer
**Blocking**: Yes - Depends on 3.3
**Estimated Time**: 3-4 days

```text
[ ] Create runtime/capabilities/coordinator.py
    [ ] Implement capability discovery
    [ ] Implement capability routing
    [ ] Implement capability execution
    [ ] Implement result aggregation

[ ] Create runtime/capabilities/registry.py
    [ ] Implement capability registration
    [ ] Implement capability lookup
    [ ] Implement capability validation
    [ ] Add health checks

[ ] Create runtime/capabilities/policy.py
    [ ] Implement capability eligibility checks
    [ ] Implement resource constraints
    [ ] Implement security policies
    [ ] Implement rate limiting

[ ] Update inference layer
    [ ] Route tool calls through coordinator
    [ ] Update tool result handling
    [ ] Update error handling
```

**Files**:
- `src/ai_karen_engine/runtime/capabilities/coordinator.py` (new)
- `src/ai_karen_engine/runtime/capabilities/registry.py` (new)
- `src/ai_karen_engine/runtime/capabilities/policy.py` (new)

### 3.5 Migrate Agent-Client Callers
**Owner**: All Teams
**Risk**: High - Breaking changes
**Blocking**: Yes - Depends on 3.2, 3.3, 3.4
**Estimated Time**: 4-5 days

```text
[ ] Migrate execute_code() callers
    [ ] Update to use PythonExecutionCapability
    [ ] Update to route through runtime coordinator
    [ ] Update error handling

[ ] Migrate search_web() callers
    [ ] Update to use WebSearchCapability
    [ ] Update to route through runtime coordinator
    [ ] Update result handling

[ ] Migrate process_document() callers
    [ ] Update to use DocumentProcessingCapability
    [ ] Update to route through runtime coordinator
    [ ] Update result handling

[ ] Migrate interpreter usage
    [ ] Update to use appropriate capabilities
    [ ] Update to route through runtime coordinator
    [ ] Update resource management

[ ] Update all imports
    [ ] Remove core/agent_client imports
    [ ] Add extensions/ imports
    [ ] Add runtime/ imports
    [ ] Update type annotations

[ ] Update tests
    [ ] Migrate test cases
    [ ] Update mocks
    [ ] Update assertions
```

### 3.6 Remove Core Agent-Client
**Owner**: Core Team
**Risk**: High - Breaking changes
**Blocking**: Yes - Depends on 3.5
**Estimated Time**: 1-2 days

```text
[ ] Remove core/agent_client/ directory
    [ ] Verify no remaining imports
    [ ] Verify no remaining dependencies
    [ ] Remove all files

[ ] Update documentation
    [ ] Remove agent_client references
    [ ] Document new capability pattern
    [ ] Update architecture diagrams

[ ] Add removal to changelog
    [ ] Document breaking changes
    [ ] Provide migration guide
    [ ] Set version bump
```

---

## Phase 4: Recall Authority Consolidation + Associative Recall

### 4.1 Audit Retrieval Systems
**Owner**: Memory Team
**Risk**: Low - Read-only operations
**Blocking**: No - Can proceed immediately
**Estimated Time**: 2 days

```text
[ ] Audit core/memory/retrieval/
    [ ] recall_manager.py responsibilities
    [ ] retrieval_router.py responsibilities
    [ ] fusion.py responsibilities
    [ ] rerank.py responsibilities

[ ] Audit core/neuro_recall/
    [ ] client/ responsibilities
    [ ] no_parametric_cbr.py responsibilities
    [ ] Strategy determination responsibilities
    [ ] Query decomposition responsibilities
    [ ] Spreading activation implementation

[ ] Audit core/reasoning/retrieval/
    [ ] vector_stores.py responsibilities
    [ ] adapters.py responsibilities
    [ ] Storage ownership assessment

[ ] Document overlap and duplication
    [ ] Identify duplicate responsibilities
    [ ] Identify conflicting implementations
    [ ] Identify missing abstractions

[ ] Propose ownership structure
    [ ] Memory: stores and exposes memory candidates
    [ ] NeuroRecall: retrieval strategy, query decomposition, fusion, reranking, spreading activation, associative recall
    [ ] Reasoning: consumes RecallPort, no storage ownership
```

**Output**: `docs/CORE-SPLIT-2-recall-audit.md`

### 4.2 Define Canonical Recall Authority
**Owner**: Memory Team
**Risk**: Medium - Interface design
**Blocking**: Yes - Required before consolidation
**Estimated Time**: 2-3 days

```text
[ ] Define RecallPort interface (core)
    [ ] query() method
    [ ] decompose() method
    [ ] fuse() method
    [ ] rerank() method
    [ ] spread_activation() method for associative recall
    [ ] retrieve_with_associations() method

[ ] Define MemoryPort interface (core)
    [ ] store() method
    [ ] retrieve() method
    [ ] update() method
    [ ] delete() method

[ ] Update core/memory/ ownership
    [ ] Keep candidate storage
    [ ] Keep memory state management
    [ ] Remove retrieval strategy
    [ ] Remove fusion logic
    [ ] Remove reranking logic

[ ] Update core/neuro_recall/ ownership
    [ ] Keep strategy determination
    [ ] Keep query decomposition
    [ ] Keep fusion implementation
    [ ] Keep reranking implementation
    [ ] Keep spreading activation implementation
    [ ] Keep associative recall implementation
    [ ] Add RecallPort implementation

[ ] Update core/reasoning/retrieval/
    [ ] Remove vector_stores.py
    [ ] Remove adapters.py (if storage-related)
    [ ] Keep reasoning-specific retrieval logic
    [ ] Consume RecallPort instead of direct storage
```

**Files**:
- `src/ai_karen_engine/core/recall/ports.py` (new)
- `src/ai_karen_engine/core/memory/ports.py` (new)
- `src/ai_karen_engine/core/neuro_recall/associative.py` (new)

### 4.3 Consolidate Memory Retrieval
**Owner**: Memory Team
**Risk**: High - Breaking changes
**Blocking**: Yes - Depends on 4.2
**Estimated Time**: 3-4 days

```text
[ ] Move retrieval strategy to neuro_recall
    [ ] Move retrieval_router.py
    [ ] Move fusion.py
    [ ] Move rerank.py
    [ ] Update imports

[ ] Create adapters for memory
    [ ] Create RecallPort adapter for memory systems
    [ ] Keep core/memory focused on storage
    [ ] Remove strategy logic

[ ] Implement associative recall in neuro_recall
    [ ] Build spreading activation graph from memory associations
    [ ] Implement activation spreading from query concepts to neighbors
    [ ] Implement RecallScore formula
    [ ] Integrate with fusion and reranking

[ ] Update memory retrieval usage
    [ ] Update all callers to use RecallPort
    [ ] Update all callers to use neuro_recall for strategy
    [ ] Update type annotations
    [ ] Update tests
```

### 4.4 Remove Reasoning Storage Ownership
**Owner**: Reasoning Team
**Risk**: Medium - Breaking changes
**Blocking**: Yes - Depends on 4.2
**Estimated Time**: 2-3 days

```text
[ ] Remove reasoning/retrieval/vector_stores.py
    [ ] Verify no storage-specific logic needed
    [ ] Move any reusable logic to appropriate owner
    [ ] Remove file

[ ] Remove reasoning/retrieval/adapters.py (if storage-related)
    [ ] Verify no storage-specific logic needed
    [ ] Move any reusable logic to appropriate owner
    [ ] Remove file

[ ] Update reasoning to consume RecallPort
    [ ] Update all retrieval calls to use RecallPort
    [ ] Update query construction
    [ ] Update result handling
    [ ] Update error handling

[ ] Update reasoning tests
    [ ] Mock RecallPort instead of storage
    [ ] Update test scenarios
    [ ] Update assertions
```

---

## Phase 5: Personalization/Adaptive Persistence Split

### 5.1 Audit Personalization Architecture
**Owner**: Personalization Team
**Risk**: Low - Read-only operations
**Blocking**: No - Can proceed immediately
**Estimated Time**: 1-2 days

```text
[ ] Audit core/personalization/persistence/repository.py
    [ ] Document in-memory dictionary implementation
    [ ] Document "canonical Postgres" claim vs reality
    [ ] Document health check falseness
    [ ] Document all dependencies

[ ] Audit personalization/ structure
    [ ] Classify components as Core or Platform
    [ ] Identify persistence components
    [ ] Identify cache components
    [ ] Identify queue components

[ ] Document health check violations
    [ ] memory_integration = READY (false)
    [ ] queue = READY (false)
    [ ] snapshot_cache = READY (false)
    [ ] evidence_processor = READY (false)

[ ] Classify personalization components
    [ ] Core: semantics, preference inference, behavior aggregation
    [ ] Core: goal reasoning, drift detection, user-model synthesis
    [ ] Platform: PersonalizationRepository, SQL persistence
    [ ] Platform: cache, queue
```

**Output**: `docs/CORE-SPLIT-2-personalization-audit.md`

### 5.2 Create Core Personalization Contracts
**Owner**: Personalization Team
**Risk**: Medium - Interface changes
**Blocking**: Yes - Required before split
**Estimated Time**: 2-3 days

```text
[ ] Create core/personalization/contracts.py
    [ ] Define PersonalizationRepository interface
    [ ] Define PreferenceModel interface
    [ ] Define UserBehavior interface
    [ ] Define GoalReasoning interface
    [ ] Define DriftDetection interface

[ ] Extract core personalization logic
    [ ] Keep preference inference logic
    [ ] Keep behavior aggregation logic
    [ ] Keep goal reasoning logic
    [ ] Keep drift detection logic
    [ ] Keep user-model synthesis logic
    [ ] Remove persistence implementation

[ ] Create core/personalization/evidence/
    [ ] Extract evidence processing logic
    [ ] Remove persistence dependencies

[ ] Create core/personalization/drift/
    [ ] Extract drift detection logic
    [ ] Remove persistence dependencies
```

**Files**:
- `src/ai_karen_engine/core/personalization/contracts.py` (new)
- `src/ai_karen_engine/core/personalization/evidence/` (refactored)
- `src/ai_karen_engine/core/personalization/drift/` (refactored)

### 5.3 Create Platform Personalization Implementation
**Owner**: Platform Team
**Risk**: Medium - New implementations
**Blocking**: Yes - Depends on 5.2
**Estimated Time**: 3-4 days

```text
[ ] Create platform/personalization/
    [ ] repository.py (real Postgres implementation)
    [ ] cache.py (real cache implementation)
    [ ] queue.py (real queue implementation)

[ ] Implement PersonalizationRepository
    [ ] Replace in-memory dict with real Postgres
    [ ] Add proper connection handling
    [ ] Add transaction management
    [ ] Add error handling
    [ ] Add real health checks

[ ] Implement cache layer
    [ ] Use real cache backend (Redis/Memcached)
    [ ] Add cache invalidation
    [ ] Add cache warming
    [ ] Add real health checks

[ ] Implement queue layer
    [ ] Use real queue backend (Redis/SQL-based)
    [ ] Add proper queue management
    [ ] Add dead letter handling
    [ ] Add real health checks

[ ] Update health checks
    [ ] Remove fake READY statuses
    [ ] Implement actual dependency health checks
    [ ] Add proper error reporting
    [ ] Add degraded state handling
```

**Files**:
- `src/ai_karen_engine/platform/personalization/repository.py` (new)
- `src/ai_karen_engine/platform/personalization/cache.py` (new)
- `src/ai_karen_engine/platform/personalization/queue.py` (new)

### 5.4 Migrate Personalization Usage
**Owner**: Personalization Team
**Risk**: High - Breaking changes
**Blocking**: Yes - Depends on 5.2, 5.3
**Estimated Time**: 2-3 days

```text
[ ] Update personalization imports
    [ ] Import from core/personalization/contracts
    [ ] Import from platform/personalization
    [ ] Update type annotations
    [ ] Update documentation

[ ] Update all callers
    [ ] Update to use PersonalizationRepository interface
    [ ] Update error handling
    [ ] Update test mocks

[ ] Remove old persistence code
    [ ] Remove core/personalization/persistence/
    [ ] Remove in-memory implementation
    [ ] Remove fake health checks
    [ ] Update all references
```

### 5.5 Audit Adaptive Architecture
**Owner**: Adaptive Team
**Risk**: Low - Read-only operations
**Blocking**: No - Can proceed immediately
**Estimated Time**: 1-2 days

```text
[ ] Audit adaptive/runtime.py
    [ ] Classify each function:
        - pure recommendation computation
        - learning state
        - runtime effect
        - provider call
        - persistence
        - external capability

[ ] Document adaptive components
    [ ] candidates/ responsibilities
    [ ] drift/ responsibilities
    [ ] learning/ responsibilities
    [ ] profiles/ responsibilities
    [ ] ranking/ responsibilities
    [ ] suggestions/ responsibilities
    [ ] runtime.py responsibilities

[ ] Create classification matrix
    [ ] Core: pure computation, learning state
    [ ] Runtime: runtime effect, provider calls
    [ ] Platform: persistence
    [ ] Extensions: external capabilities
```

**Output**: `docs/CORE-SPLIT-2-adaptive-audit.md`

### 5.6 Split Adaptive Runtime
**Owner**: Adaptive Team
**Risk**: Medium - Breaking changes
**Blocking**: Yes - Depends on 5.5
**Estimated Time**: 2-3 days

```text
[ ] Extract pure recommendation computation
    [ ] Keep ranking algorithms in core/adaptive/
    [ ] Keep candidate generation in core/adaptive/
    [ ] Keep suggestion logic in core/adaptive/

[ ] Extract learning state management
    [ ] Keep learning logic in core/adaptive/
    [ ] Keep drift detection in core/adaptive/
    [ ] Keep profile management in core/adaptive/

[ ] Move runtime effects to runtime/adaptive/
    [ ] Move runtime effect execution
    [ ] Move provider calls
    [ ] Move external capability calls

[ ] Move persistence to platform/adaptive/
    [ ] Move persistence operations
    [ ] Move cache operations
    [ ] Add real health checks

[ ] Remove execution authority from adaptive
    [ ] Verify no direct provider calls in core
    [ ] Verify no direct persistence in core
    [ ] Verify no external capability calls in core
```

**Files**:
- `src/ai_karen_engine/runtime/adaptive/` (new)
- `src/ai_karen_engine/platform/adaptive/` (new)

---

## Phase 6: Context & Prompt Assembly Split

### 6.1 Create Core Context Reasoning
**Owner**: Context Team
**Risk**: Medium - Interface changes
**Blocking**: Yes - Required before split
**Estimated Time**: 2-3 days

```text
[ ] Create core/context/contracts.py
    [ ] Define ContextPlan interface
    [ ] Define ContextRequirement interface
    [ ] Define ContextBudget interface
    [ ] Define RelevanceStrategy interface

[ ] Create core/context/reasoning/
    [ ] Extract relevance determination logic
    [ ] Extract memory ranking logic
    [ ] Extract evidence selection logic
    [ ] Extract budget allocation logic
    [ ] Extract contradiction detection logic

[ ] Create ContextPlan builder
    [ ] Implement plan construction logic
    [ ] Implement budget allocation logic
    [ ] Implement priority ordering
    [ ] Remove any fetching operations
```

**Files**:
- `src/ai_karen_engine/core/context/contracts.py` (new)
- `src/ai_karen_engine/core/context/reasoning/` (new)

### 6.2 Create Runtime Context Materialization
**Owner**: Runtime Team
**Risk**: Medium - New implementations
**Blocking**: Yes - Depends on 6.1
**Estimated Time**: 2-3 days

```text
[ ] Create runtime/context/assembler.py
    [ ] Implement ContextAssembler.materialize()
    [ ] Implement memory fetching
    [ ] Implement file fetching
    [ ] Implement tool result fetching
    [ ] Implement tenant profile loading
    [ ] Implement conversation loading
    [ ] Implement external retrieval calls

[ ] Create runtime/context/truncation.py
    [ ] Implement token budget enforcement
    [ ] Implement context truncation strategies
    [ ] Implement priority-based dropping

[ ] Create runtime/context/provider_adapter.py
    [ ] Implement provider-specific message preparation
    [ ] Implement message formatting
    [ ] Remove core dependencies
```

**Files**:
- `src/ai_karen_engine/runtime/context/assembler.py` (new)
- `src/ai_karen_engine/runtime/context/truncation.py` (new)
- `src/ai_karen_engine/runtime/context/provider_adapter.py` (new)

### 6.3 Create Core Prompt Policy
**Owner**: Prompt Team
**Risk**: Medium - Interface changes
**Blocking**: Yes - Required before split
**Estimated Time**: 2-3 days

```text
[ ] Create core/prompt_policy/contracts.py
    [ ] Define PromptContract interface
    [ ] Define PromptPolicy interface
    [ ] Define InstructionPrecedence interface
    [ ] Define TokenBudgetStrategy interface

[ ] Create core/prompt_policy/instruction.py
    [ ] Extract instruction precedence logic
    [ ] Extract persona semantics
    [ ] Extract trust classification

[ ] Create core/prompt_policy/context.py
    [ ] Extract context requirements logic
    [ ] Extract tool/capability declarations

[ ] Create core/prompt_policy/budget.py
    [ ] Extract token budget strategy logic
    [ ] Extract budget allocation logic
```

**Files**:
- `src/ai_karen_engine/core/prompt_policy/contracts.py` (new)
- `src/ai_karen_engine/core/prompt_policy/instruction.py` (new)
- `src/ai_karen_engine/core/prompt_policy/context.py` (new)
- `src/ai_karen_engine/core/prompt_policy/budget.py` (new)

### 6.4 Create Runtime Prompt Rendering
**Owner**: Runtime Team
**Risk**: Medium - New implementations
**Blocking**: Yes - Depends on 6.3
**Estimated Time**: 2-3 days

```text
[ ] Create runtime/prompt/renderer.py
    [ ] Implement OpenAI message construction
    [ ] Implement Anthropic message formatting
    [ ] Implement Gemini request formatting
    [ ] Implement template rendering
    [ ] Implement tool schema serialization

[ ] Create runtime/prompt/adapter.py
    [ ] Implement provider-specific adaptations
    [ ] Implement message validation
    [ ] Remove core dependencies
```

**Files**:
- `src/ai_karen_engine/runtime/prompt/renderer.py` (new)
- `src/ai_karen_engine/runtime/prompt/adapter.py` (new)

---

## Phase 7: Learning Trajectory Split

### 7.1 Create Core Learning Contracts
**Owner**: Learning Team
**Risk**: Medium - Interface changes
**Blocking**: Yes - Required before split
**Estimated Time**: 2-3 days

```text
[ ] Create core/learning/contracts.py
    [ ] Define LearningSignal interface
    [ ] Define OutcomeSignal interface
    [ ] Define RewardSignal interface
    [ ] Define TrajectorySemantic interface
    [ ] Define TrainingExampleCandidate interface

[ ] Extract semantic learning logic
    [ ] Keep signal semantics in core/learning/
    [ ] Keep outcome analysis in core/learning/
    [ ] Keep reward computation in core/learning/
    [ ] Keep trajectory semantics in core/learning/
    [ ] Remove recording/storage logic
```

**Files**:
- `src/ai_karen_engine/core/learning/contracts.py` (new)

### 7.2 Create Runtime Trajectory Recording
**Owner**: Runtime Team
**Risk**: Medium - New implementations
**Blocking**: Yes - Depends on 7.1
**Estimated Time**: 2-3 days

```text
[ ] Create runtime/trajectory/recorder.py
    [ ] Implement execution recording
    [ ] Implement timestamp collection
    [ ] Implement provider metadata collection
    [ ] Implement tool metadata collection
    [ ] Implement request correlation

[ ] Remove storage logic from runtime
    [ ] Move store operations to platform
    [ ] Move dataset persistence to platform
    [ ] Keep recording logic in runtime
```

**Files**:
- `src/ai_karen_engine/runtime/trajectory/recorder.py` (refactored)

### 7.3 Create Platform Trajectory Storage
**Owner**: Platform Team
**Risk**: Medium - New implementations
**Blocking**: Yes - Depends on 7.1
**Estimated Time**: 2-3 days

```text
[ ] Create platform/trajectory/store.py
    [ ] Implement trajectory storage
    [ ] Implement dataset persistence
    [ ] Implement artifact file management
    [ ] Add real health checks
```

**Files**:
- `src/ai_karen_engine/platform/trajectory/store.py` (new)

---

## Phase 8: Reasoning Model Execution Audit

### 8.1 Audit Reasoning Model Usage
**Owner**: Reasoning Team
**Risk**: Low - Read-only operations
**Blocking**: No - Can proceed immediately
**Estimated Time**: 1-2 days

```text
[ ] Audit reasoning/synthesis/small_language_model_service.py
    [ ] Document model instantiation
    [ ] Document provider selection
    [ ] Document device selection
    [ ] Document transformer invocation
    [ ] Document all dependencies

[ ] Classify reasoning model usage
    [ ] Legitimate inference requirements (keep)
    [ ] Provider instantiation (move to runtime)
    [ ] Model selection (move to runtime)
    [ ] Device management (move to runtime)

[ ] Document required interfaces
    [ ] InferencePort interface requirements
    [ ] Model metadata requirements
    [ ] Provider selection requirements
```

**Output**: `docs/CORE-SPLIT-2-reasoning-model-audit.md`

### 8.2 Create Inference Port for Reasoning
**Owner**: Runtime Team
**Risk**: Medium - Interface design
**Blocking**: Yes - Required before audit completion
**Estimated Time**: 2-3 days

```text
[ ] Create runtime/inference/ports.py
    [ ] Define InferencePort interface
    [ ] Define ModelSelectionStrategy interface
    [ ] Define ProviderSelectionStrategy interface

[ ] Create runtime/inference/coordinator.py
    [ ] Implement inference routing
    [ ] Implement provider selection
    [ ] Implement model selection
    [ ] Implement device management

[ ] Update reasoning to use InferencePort
    [ ] Remove direct model instantiation
    [ ] Remove direct provider selection
    [ ] Use InferencePort for all inference
    [ ] Update error handling
```

**Files**:
- `src/ai_karen_engine/runtime/inference/ports.py` (new)
- `src/ai_karen_engine/runtime/inference/coordinator.py` (new)

### 8.3 Refactor Reasoning Model Service
**Owner**: Reasoning Team
**Risk**: Medium - Breaking changes
**Blocking**: Yes - Depends on 8.2
**Estimated Time**: 2-3 days

```text
[ ] Refactor small_language_model_service.py
    [ ] Remove model instantiation
    [ ] Remove provider selection
    [ ] Remove device management
    [ ] Use InferencePort for all inference
    [ ] Keep reasoning-specific logic

[ ] Update reasoning tests
    [ ] Mock InferencePort instead of models
    [ ] Update test scenarios
    [ ] Update assertions
```

---

## Phase 9: Error Handling & Observability Reorganization

### 9.1 Split Error Handling
**Owner**: All Teams
**Risk**: Medium - Breaking changes
**Blocking**: Yes - Required for proper separation
**Estimated Time**: 2-3 days

```text
[ ] Create core/contracts/errors.py
    [ ] Define semantic error types
        - MemoryRecallUnavailable
        - CapabilityNotEligible
        - InferenceRequirementUnsatisfied
        - ContextBudgetExceeded
    [ ] Remove HTTP-specific errors

[ ] Create runtime/errors/
    [ ] Define runtime error types
    [ ] Define runtime exception hierarchy
    [ ] Add runtime-specific error handling

[ ] Create api/errors/
    [ ] Define HTTP translation layer
    [ ] Define status code mapping
    [ ] Define error response formatting

[ ] Create platform/errors/
    [ ] Define infrastructure error types
    [ ] Define database errors
    [ ] Define storage errors
    [ ] Add platform-specific error handling

[ ] Remove core/errors/
    [ ] Remove handlers.py
    [ ] Remove middleware.py
    [ ] Remove response_validation.py
    [ ] Update all imports
```

**Files**:
- `src/ai_karen_engine/core/contracts/errors.py` (new)
- `src/ai_karen_engine/runtime/errors/` (new)
- `src/ai_karen_engine/api/errors/` (new)
- `src/ai_karen_engine/platform/errors/` (new)

### 9.2 Move Observability Out of Core
**Owner**: Observability Team
**Risk**: Medium - Breaking changes
**Blocking**: Yes - Required for proper separation
**Estimated Time**: 2-3 days

```text
[ ] Create observability/ directory at top level
    [ ] Move core/logging/ to observability/logging/
    [ ] Move core/observability/ to observability/
    [ ] Update all imports

[ ] Create observability/contracts.py
    [ ] Define observability interfaces
    [ ] Define telemetry interfaces
    [ ] Define monitoring interfaces

[ ] Update core to use observability interfaces
    [ ] Import from observability/contracts
    [ ] Remove implementation dependencies
    [ ] Update type annotations
```

**Files**:
- `src/ai_karen_engine/observability/` (new)
- `src/ai_karen_engine/observability/contracts.py` (new)

### 9.3 Move Security Out of Core
**Owner**: Security Team
**Risk**: Medium - Breaking changes
**Blocking**: Yes - Required for proper separation
**Estimated Time**: 2-3 days

```text
[ ] Create security/ directory at top level
    [ ] Move any security logic from core/
    [ ] Create security/contracts.py
    [ ] Define security interfaces
    [ ] Define RBAC interfaces
    [ ] Define authorization interfaces

[ ] Update CORTEX RBAC wording
    [ ] Ensure CORTEX only produces eligibility
    [ ] Ensure Runtime enforces authorization
    [ ] Ensure Platform authenticates
    [ ] Update documentation

[ ] Update core to use security interfaces
    [ ] Import from security/contracts
    [ ] Remove implementation dependencies
    [ ] Update type annotations
```

**Files**:
- `src/ai_karen_engine/security/` (new)
- `src/ai_karen_engine/security/contracts.py` (new)

---

## Phase 10: LangGraph Integration Update

### 10.1 Audit LangGraph Tool Execution
**Owner**: Runtime Team
**Risk**: Low - Read-only operations
**Blocking**: No - Can proceed immediately
**Estimated Time**: 1-2 days

```text
[ ] Audit LangGraph tool execution paths
    [ ] Document direct tool calls
    [ ] Document capability invocations
    [ ] Document provider interactions
    [ ] Document security checks

[ ] Classify LangGraph tool usage
    [ ] Core reasoning (keep)
    [ ] Tool execution (move to runtime)
    [ ] Provider calls (move to runtime)
    [ ] Security enforcement (move to runtime)
```

**Output**: `docs/CORE-SPLIT-2-langgraph-audit.md`

### 10.2 Update LangGraph Tool Execution
**Owner**: Runtime Team
**Risk**: Medium - Breaking changes
**Blocking**: Yes - Depends on 10.1
**Estimated Time**: 2-3 days

```text
[ ] Update LangGraph to delegate to Runtime
    [ ] Route all tool calls through runtime coordinator
    [ ] Route all capability calls through runtime
    [ ] Remove direct tool execution
    [ ] Remove direct provider calls

[ ] Update LangGraph security checks
    [ ] Move authorization checks to Runtime
    [ ] Move RBAC enforcement to Runtime
    [ ] Keep eligibility checks in CORTEX

[ ] Update LangGraph tests
    [ ] Mock runtime coordinator
    [ ] Update test scenarios
    [ ] Update assertions
```

---

## Phase 11: Extension Isolation & Future-Proofing

### 11.1 Design Extension Manifest
**Owner**: Extensions Team
**Risk**: Low - Design only
**Blocking**: No - Can proceed immediately
**Estimated Time**: 2-3 days

```text
[ ] Design ExtensionManifest structure
    [ ] Define capability declarations
    [ ] Define version support
    [ ] Define deprecation support
    [ ] Define execution types (NATIVE, SUBPROCESS, CONTAINER, MCP, A2A, WASI, REMOTE)

[ ] Design extension discovery
    [ ] Define manifest loading
    [ ] Define capability registration
    [ ] Define version validation
    [ ] Define deprecation handling

[ ] Design extension isolation
    [ ] Define execution type interfaces
    [ ] Define security constraints
    [ ] Define resource limits
    [ ] Define health checks
```

**Files**:
- `src/ai_karen_engine/extensions/manifest.py` (design)
- `src/ai_karen_engine/extensions/discovery.py` (design)

### 11.2 Create Protocol Adapters
**Owner**: Extensions Team
**Risk**: Medium - New implementations
**Blocking**: Yes - Depends on 11.1
**Estimated Time**: 3-4 days

```text
[ ] Create extensions/mcp/adapter.py
    [ ] Implement MCP protocol adapter
    [ ] Map MCP capabilities to extension contracts
    [ ] Add MCP-specific error handling
    [ ] Add MCP health checks

[ ] Create extensions/a2a/adapter.py
    [ ] Implement A2A protocol adapter
    [ ] Map A2A capabilities to extension contracts
    [ ] Add A2A-specific error handling
    [ ] Add A2A health checks

[ ] Update extension registry
    [ ] Register MCP adapters
    [ ] Register A2A adapters
    [ ] Add protocol-specific routing
```

**Files**:
- `src/ai_karen_engine/extensions/mcp/adapter.py` (new)
- `src/ai_karen_engine/extensions/a2a/adapter.py` (new)

### 11.3 Design Toward WASI (Not Implement)
**Owner**: Extensions Team
**Risk**: Low - Design only
**Blocking**: No - Can proceed immediately
**Estimated Time**: 1-2 days

```text
[ ] Design WASI execution type interface
    [ ] Define WASI component execution interface
    [ ] Define security constraints
    [ ] Define resource limits
    [ ] Define health checks

[ ] Update ExtensionManifest to support WASI
    [ ] Add WASI execution type
    [ ] Add WASI-specific constraints
    [ ] Add WASI-specific metadata

[ ] Document WASI future implementation
    [ ] Create implementation roadmap
    [ ] Define requirements
    [ ] Define timeline
```

**Output**: `docs/CORE-SPLIT-2-wasi-roadmap.md`

---

## Phase 12: Final Architecture Test Enforcement

### 12.1 Update Architecture Tests
**Owner**: Architecture Team
**Risk**: Low - Test updates only
**Blocking**: Yes - Required for completion
**Estimated Time**: 2-3 days

```text
[ ] Add CORE ↛ PLATFORM rule (hard fail)
[ ] Add CORE ↛ PROVIDERS rule (hard fail)
[ ] Add CORE ↛ EXTENSIONS rule (hard fail)
[ ] Add CORE ↛ RUNTIME rule (hard fail)
[ ] Add RUNTIME ↛ CORE rule (hard fail)

[ ] Update all xfails
    [ ] Add owner to each xfail
    [ ] Add migration sprint to each xfail
    [ ] Add sunset condition to each xfail
    [ ] Add expiry to each xfail
    [ ] Set maximum expiry: 2 sprints

[ ] Remove expired xfails
    [ ] Convert expired xfails to hard fails
    [ ] Update documentation
    [ ] Update migration plans
```

**Files**: `tests/architecture/`

### 12.2 Run Full Architecture Test Suite
**Owner**: Architecture Team
**Risk**: Low - Test execution only
**Blocking**: Yes - Required for completion
**Estimated Time**: 1 day

```text
[ ] Run full architecture test suite
[ ] Document all failures
[ ] Classify failures by severity
[ ] Create remediation plans
[ ] Update completion gate
```

---

---

## Cognitive Continuity Invariant

Add the following to `ARCHITECTURE.md` as a first-class architectural requirement:

> **Cognitive Continuity Invariant**
>
> Karen's behavior MUST be capable of being influenced by relevant prior experience, learned user knowledge, temporal state, active goals, relationships, unresolved intentions, and consolidated learning without requiring raw conversation history to remain in the model context.
>
> Memory retrieval MUST NOT depend solely on vector similarity.
>
> Durable beliefs MUST retain provenance, confidence, temporal validity, and contradiction/supersession relationships.
>
> Episodic memory, semantic consolidation, associative recall, temporal reasoning, and controlled forgetting are Core cognitive responsibilities.
>
> Concrete storage, vector databases, caches, graph databases, embedding implementations, and scheduling infrastructure are not Core.

---

## Completion Gate Checklist

**All items must pass before CORE-SPLIT-2 is considered complete**

### Core Purity
```text
[ ] Core imports no UI-specific memory models
[ ] Core memory imports no concrete Postgres client
[ ] Core memory imports no SQLAlchemy
[ ] Core memory does not construct EmbeddingManager
[ ] Core imports no provider implementations
[ ] Core imports no extension implementations
[ ] Core error middleware removed
[ ] Core observability implementation removed
[ ] Core security mechanics removed
```

### Runtime Authority
```text
[ ] core/agent_client removed or fully de-authoritized
[ ] Interpreters are extensions/runtime capabilities
[ ] SearchTool is not invoked directly from Core
[ ] DocumentsTool is not invoked directly from Core
[ ] LangGraph tool execution delegates to Runtime
[ ] Adaptive runtime has no execution authority
[ ] Reasoning model calls use InferencePort
```

### Recall Authority
```text
[ ] One recall authority exists
[ ] Reasoning retrieval doesn't own storage
[ ] Memory storage adapters outside cognitive domain
[ ] NeuroRecall owns spreading activation and associative recall
[ ] RecallScore uses semantic + associative + temporal + salience + relationship + goal + repetition + causal + unresolved intention + explicit priority - contradiction - staleness - interference
```

### Personalization/Adaptive
```text
[ ] Personalization repository implementation moved out
[ ] Health reports are evidence-backed
[ ] Adaptive persistence moved to platform
```

### Cognitive Architecture
```text
[ ] Memory lifecycle defined: PERCEIVE → ENCODE → SCORE_SALIENCE → ASSOCIATE → STORE_EPISODE → REPLAY_REFLECT → CONSOLIDATE → GENERALIZE → RETRIEVE → RECONSOLIDATE → DECAY_SUPERSEDE_FORGET
[ ] All 12 memory types implemented: Working, Episodic, Semantic, Autobiographical, Preference, Procedural, Prospective, Relational, Temporal, Salience, Belief, Meta-memory
[ ] MemoryClaim model implemented with confidence, provenance, evidence, temporal validity, contradiction_refs, supersedes, status
[ ] ClaimStatus enum implemented: OBSERVED, INFERRED, USER_ASSERTED, VERIFIED, DISPUTED, SUPERSEDED, STALE, RETRACTED
[ ] SelfModel, UserModel, RelationshipModel implemented and governed
[ ] ProspectiveMemory implemented with trigger-based resurfacing
[ ] ReflectionEngine implemented with evidence checking and promotion gates
[ ] Controlled forgetting implemented: decay, suppression, consolidation
[ ] Reconsolidation preserves provenance while revising interpretation
[ ] Memory feeds CORTEX decisions, not just prompt text
```

### Architecture Tests
```text
[ ] Core architecture tests enforce all rules
[ ] No xfails without owner, sprint, sunset, expiry
[ ] All xfails have expiry < 2 sprints
[ ] All architecture tests pass
```

### Cognitive Proof Suite
```text
[ ] recalls explicit user preference after session boundary
[ ] retrieves related memory without lexical overlap
[ ] newer preference supersedes older preference
[ ] old episode remains available as provenance
[ ] distinguishes event time from conversation time
[ ] repeated episodes consolidate into semantic memory
[ ] one isolated event does not become strong user preference
[ ] contradictory memories lower confidence
[ ] unresolved intention can resurface when relevant
[ ] irrelevant old memories decay in retrieval rank
[ ] high-salience decision survives longer than trivial detail
[ ] recall spans associative graph neighbors
[ ] retrieved memories influence CORTEX action selection
[ ] CORTEX cannot treat inferred memory as verified fact
[ ] cross-tenant memories can never activate
[ ] deleted/retracted memories cannot reappear from vector/graph indexes
[ ] memory reconstruction preserves provenance
[ ] provider replacement does not change memory semantics
[ ] Redis/Milvus outage degrades honestly rather than inventing recall
```

---

## Rollback Procedures

### If Phase 2 (Memory) Fails
```text
1. Revert memory decontamination changes
2. Restore original memory_service.py
3. Restore original imports
4. Update documentation
5. Schedule retry for next sprint
```

### If Phase 3 (Agent-Client) Fails
```text
1. Restore core/agent_client/ directory
2. Revert capability migration
3. Restore original imports
4. Update documentation
5. Schedule retry for next sprint
```

### If Any Phase Fails
```text
1. Stop all dependent phases
2. Revert completed changes in current phase
3. Document failure points
4. Update architecture tests (add temporary xfail with expiry)
5. Schedule retry for next sprint
```

---

## Documentation Updates

### Required Documentation
```text
[ ] Update README.md with new architecture
[ ] Update architecture diagrams
[ ] Create migration guide for breaking changes
[ ] Update API documentation
[ ] Update contributor guide
[ ] Create troubleshooting guide
[ ] Update changelog with breaking changes
```

### Developer Communication
```text
[ ] Announce CORE-SPLIT-2 changes
[ ] Provide migration timeline
[ ] Provide support resources
[ ] Schedule office hours
[ ] Update onboarding materials
```

---

## Success Metrics

### Architecture Purity
```text
- Zero Core → Platform/Provider/Extension imports
- Zero architecture test xfails beyond 2 sprints
- 100% of health checks are evidence-backed
```

### Cognitive Architecture
```text
- Memory lifecycle contracts enforce PERCEIVE → ENCODE → SCORE_SALIENCE → ASSOCIATE → STORE_EPISODE → REPLAY_REFLECT → CONSOLIDATE → GENERALIZE → RETRIEVE → RECONSOLIDATE → DECAY_SUPERSEDE_FORGET
- All 12 memory types have Core contracts and Platform implementations
- MemoryClaim model with temporal validity and contradiction tracking
- SelfModel, UserModel, RelationshipModel governed and isolated
- ProspectiveMemory trigger-based resurfacing works
- ReflectionEngine promotes/defer/rejects with evidence checking
- Controlled forgetting: decay, suppression, consolidation
- Reconsolidation preserves provenance while revising interpretation
- Recall uses associative spreading activation, not just vector similarity
- Memory feeds CORTEX decisions, not just prompt text
- Cognitive proof suite: 19/19 criteria pass
```

### Code Quality
```text
- All new code passes linting
- All new code passes type checking
- All new code has >80% test coverage
```

### Performance
```text
- No performance regression >5%
- No latency regression >10ms p95
- No memory regression >10%
```

### Stability
```text
- Zero critical bugs in production
- Zero breaking changes not documented
- Zero deprecation warnings not resolved
```

---

## Timeline Estimate

### Phase 1: Foundation & Safety - 1 week
### Phase 2: Memory Decontamination + Cognitive Architecture - 3 weeks
### Phase 3: Agent-Client Retirement - 2 weeks
### Phase 4: Recall Authority Consolidation + Associative Recall - 2 weeks
### Phase 5: Personalization/Adaptive Split - 2 weeks
### Phase 6: Context & Prompt Split - 1 week
### Phase 7: Learning Trajectory Split - 1 week
### Phase 8: Reasoning Model Audit - 1 week
### Phase 9: Error & Observability Reorg - 1 week
### Phase 10: LangGraph Update - 1 week
### Phase 11: Extension Isolation - 1 week
### Phase 12: Final Architecture Tests - 1 week

**Total Estimated Time: 17 weeks**

---

## Risk Assessment

### High Risk
- Memory decontamination + cognitive architecture (Phase 2)
- Agent-client retirement (Phase 3)
- Personalization persistence split (Phase 5)
- Cognitive proof suite validation (Phase 2.5)

### Medium Risk
- Recall authority consolidation (Phase 4)
- Context & prompt split (Phase 6)
- Error handling reorganization (Phase 9)

### Low Risk
- Foundation & safety (Phase 1)
- Learning trajectory split (Phase 7)
- Reasoning model audit (Phase 8)
- LangGraph update (Phase 10)
- Extension isolation (Phase 11)
- Final architecture tests (Phase 12)

---

## Next Steps

1. **Review this dev sheet** with all team leads
2. **Assign owners** to each phase
3. **Create detailed task breakdowns** for each phase
4. **Set up CI/CD** for architecture test enforcement
5. **Create feature branch** and begin Phase 1
6. **Monitor progress** weekly with architecture team
7. **Adjust timeline** as needed based on discoveries