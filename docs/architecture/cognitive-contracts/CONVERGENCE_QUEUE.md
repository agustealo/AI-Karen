# Convergence Queue

Every problem found during the cognitive contract audit, recorded for systematic resolution.

## COG-CONTRACT-001
- **Severity:** P1
- **Concept:** ReasoningDepth
- **Current owner:** reasoning/meta + cortex
- **Duplicate/conflict:** IDENTICAL_DUPLICATE enum
- **Canonical owner:** reasoning contracts
- **Affected files:** reasoning/meta/contracts.py, cortex/contracts.py
- **Recommended action:** Re-export ReasoningDepth from reasoning contracts during COG-CLOSE-1; remove duplicate from cortex
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-002
- **Severity:** P1
- **Concept:** ClaimStatus
- **Current owner:** memory + reasoning/belief
- **Duplicate/conflict:** SEMANTICALLY_DIFFERENT (belief adds UNKNOWN)
- **Canonical owner:** memory contracts
- **Affected files:** memory/contracts.py, reasoning/belief/contracts.py
- **Recommended action:** Canonicalize in memory; belief imports and maps to it; add UNKNOWN to memory ClaimStatus if needed
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-003
- **Severity:** P1
- **Concept:** EvidenceType
- **Current owner:** reasoning/belief + personalization/goals
- **Duplicate/conflict:** IDENTICAL_DUPLICATE enum
- **Canonical owner:** reasoning/belief contracts
- **Affected files:** reasoning/belief/contracts.py, personalization/goals/contracts.py
- **Recommended action:** Re-export from reasoning/belief; goals imports it
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-004
- **Severity:** P2
- **Concept:** GoalState / UserGoalStatus
- **Current owner:** personalization + personalization/goals
- **Duplicate/conflict:** SEMANTICALLY_DIFFERENT (GoalState is richer)
- **Canonical owner:** personalization/goals
- **Affected files:** personalization/contracts.py, personalization/goals/contracts.py
- **Recommended action:** Converge during COG-CLOSE-1; GoalState supersedes UserGoalStatus
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-005
- **Severity:** P2
- **Concept:** SuggestionFeedbackType
- **Current owner:** adaptive + adaptive/suggestions
- **Duplicate/conflict:** IDENTICAL_DUPLICATE enum
- **Canonical owner:** adaptive contracts
- **Affected files:** adaptive/contracts.py, adaptive/suggestions/contracts.py
- **Recommended action:** Remove duplicate from suggestions; import from adaptive
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-006
- **Severity:** P2
- **Concept:** DriftState / DriftStatus
- **Current owner:** personalization + adaptive/drift
- **Duplicate/conflict:** SEMANTICALLY_DIFFERENT
- **Canonical owner:** adaptive/drift
- **Affected files:** personalization/contracts.py, adaptive/drift/__init__.py
- **Recommended action:** Rename personalization DriftState to PreferenceDriftState to avoid confusion
- **Target sprint:** COG-CONFIG-1

## COG-CONTRACT-007
- **Severity:** P1
- **Concept:** Verification authority
- **Current owner:** reasoning/meta + cortex/behavior
- **Duplicate/conflict:** Independent verification logic in two subsystems
- **Canonical owner:** reasoning contracts (defines requirement); cortex/behavior (decides)
- **Affected files:** reasoning/meta/verification.py, cortex/behavior/verification.py, reasoning/meta/contracts.py, cortex/behavior/contracts.py
- **Recommended action:** Meta-cognition recommends verification need via MetaCognitiveResult.verification_need; CORTEX behavior decides via VerificationRequirement; runtime executes. Remove independent decider from meta.
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-008
- **Severity:** P1
- **Concept:** Public boundary loose dictionaries
- **Current owner:** cortex
- **Duplicate/conflict:** belief_assessment, goal_state, context_plan, salience, memory_signals, user_model, relationship_context, adaptive_recommendations, reasoning_assessment, policy_constraints all typed as dict[str, Any]
- **Canonical owner:** cortex/behavior contracts
- **Affected files:** cortex/behavior/contracts.py, cortex/contracts.py
- **Recommended action:** Replace dict[str, Any] with typed dataclasses at public API boundaries during COG-CLOSE-1
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-009
- **Severity:** P2
- **Concept:** Confidence overload
- **Current owner:** 30+ float fields across all cognitive domains
- **Duplicate/conflict:** No single definition; "confidence" means different things in different contexts
- **Canonical owner:** reasoning/belief
- **Affected files:** reasoning/belief/contracts.py, adaptive/contracts.py, cortex/contracts.py, personalization/contracts.py
- **Recommended action:** Introduce typed confidence wrappers (EpistemicConfidence, RetrievalConfidence, etc.) during COG-CONFIG-1
- **Target sprint:** COG-CONFIG-1

## COG-CONTRACT-010
- **Severity:** P2
- **Concept:** Tenant scope defaults
- **Current owner:** adaptive, reasoning, cortex
- **Duplicate/conflict:** Multiple contracts default tenant_id to "default"
- **Canonical owner:** core security / runtime
- **Affected files:** adaptive/contracts.py, adaptive/salience/contracts.py, cortex/behavior/contracts.py, reasoning/contracts.py, reasoning/meta/contracts.py
- **Recommended action:** Remove "default" tenant_id defaults; require explicit tenant_id in all security-sensitive contracts
- **Target sprint:** COG-CONFIG-1

## COG-CONTRACT-011
- **Severity:** P3
- **Concept:** Temporal type inconsistency
- **Current owner:** reasoning, adaptive, memory
- **Duplicate/conflict:** timestamp field typed as float, str, or datetime across domains
- **Canonical owner:** memory contracts
- **Affected files:** reasoning/contracts.py, adaptive/contracts.py, memory/types/base.py, reasoning/meta/contracts.py
- **Recommended action:** Standardize all temporal fields to datetime with UTC timezone
- **Target sprint:** COG-CONFIG-1

## COG-CONTRACT-012
- **Severity:** P2
- **Concept:** ID cross-domain misuse
- **Current owner:** adaptive/salience
- **Duplicate/conflict:** MemorySalienceSignal carries memory_id; risk of goal_id being passed as memory_id
- **Canonical owner:** adaptive/salience
- **Affected files:** adaptive/salience/contracts.py
- **Recommended action:** Add static test flagging cross-domain ID misuse; enforce distinct ID prefixes in contracts
- **Target sprint:** COG-CONTRACT-AUDIT-1 (this sprint)

## COG-CONTRACT-013
- **Severity:** P2
- **Concept:** Forbidden provider imports in cognitive packages
- **Current owner:** memory, neuro_recall, reasoning, adaptive, cortex
- **Duplicate/conflict:** requests, sqlalchemy, openai, ollama, vllm imported in cognitive implementation modules
- **Canonical owner:** platform/repos
- **Affected files:** memory/memory_runtime_manager.py, memory/unified_memory_service.py, neuro_recall/client/*.py, reasoning/kro_orchestrator.py, cortex/analysis/spacy_analyzer.py
- **Recommended action:** Move provider imports behind provider boundary; cognitive packages must not import FastAPI, SQLAlchemy, Redis client, OpenAI SDK, Ollama client, vLLM, requests/httpx
- **Target sprint:** COG-CLOSE-1

## COG-CONTRACT-014
- **Severity:** P3
- **Concept:** Missing superseded_at / deleted_at
- **Current owner:** memory, belief, goals
- **Duplicate/conflict:** Soft-delete lifecycle incomplete
- **Canonical owner:** memory contracts
- **Affected files:** memory/contracts.py, reasoning/belief/contracts.py, personalization/goals/contracts.py
- **Recommended action:** Add superseded_at and deleted_at to MemoryClaim, BeliefClaim, Goal
- **Target sprint:** COG-CONFIG-1

## COG-CONTRACT-015
- **Severity:** P3
- **Concept:** Any usage in contracts
- **Current owner:** all cognitive contracts
- **Duplicate/conflict:** Any used for metadata, object, and external payloads
- **Canonical owner:** N/A (acceptable at adaptation edges)
- **Affected files:** All contract files
- **Recommended action:** Any is acceptable in metadata bags; must not appear in core cognitive state fields
- **Target sprint:** COG-CONTRACT-AUDIT-1 (this sprint)
