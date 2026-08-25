"""
Core Memory Domain for AI Karen Engine.

Runtime authority note:
- ``ai_karen_engine.core.memory`` remains the public memory-domain facade.
- Cognitive contracts are import-safe and do not initialize runtime/platform
  dependencies as a side effect.
- Runtime, persistence, retrieval, evaluation, and compatibility exports are
  resolved lazily when callers explicitly request them.
- Legacy ``core.neuro_vault`` remains migration/compatibility scope only.

Cognitive architecture:
- 12 memory types: Working, Episodic, Semantic, Autobiographical, Preference,
  Procedural, Prospective, Relational, Temporal, Salience, Belief, Meta
- Memory lifecycle: PERCEIVE → ENCODE → SCORE_SALIENCE → ASSOCIATE →
  STORE_EPISODE → REPLAY_REFLECT → CONSOLIDATE → GENERALIZE → RETRIEVE →
  RECONSOLIDATE → DECAY_SUPERSEDE_FORGET
- Memory claims with confidence, provenance, temporal validity, contradictions
- Spreading activation and associative recall
- Controlled forgetting: decay, suppression, consolidation
- Self model, user model, relationship model
- Prospective memory (intentions, commitments)
- Reflection engine (evidence checking, promotion gates)
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Pure cognitive contracts are the only eager package-root exports. Importing
# ``ai_karen_engine.core.memory.contracts`` must never initialize persistence,
# observability, provider, or runtime infrastructure.
from .contracts import (
    ClaimStatus,
    MemoryClaim,
    MemoryLifecycleState,
    ProspectiveMemory,
    RecallScoreComponents,
    RelationshipModel,
    SalienceScore,
    SelfModel,
    UserModel,
)
from .policy import (
    ConsolidationPolicy,
    ForgettingPolicy,
    RetrievalPolicy,
    SaliencePolicy,
)
from .types import (
    AssociativeActivation,
    CognitiveMemoryEntry,
    CognitiveMemoryType,
    MemoryContext,
    ReflectionCandidate,
)

# Package-root compatibility exports. These symbols historically lived behind
# eager imports in this module. Keeping them lazy preserves the API while
# preventing a contract import from pulling platform/runtime authority into the
# cognitive kernel.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Runtime authority.
    "MemoryRuntimeManager": (".memory_runtime_manager", "MemoryRuntimeManager"),
    "get_memory_manager": (".memory_runtime_manager", "get_memory_manager"),
    "init_memory": (".memory_runtime_manager", "init_memory"),
    "close": (".memory_runtime_manager", "close"),
    "recall_context": (".memory_runtime_manager", "recall_context"),
    "update_memory": (".memory_runtime_manager", "update_memory"),
    "get_metrics": (".memory_runtime_manager", "get_metrics"),
    # Legacy ledger compatibility. The module itself owns its deprecation path.
    "ConsentScope": (".ledger_models", "ConsentScope"),
    "ContradictionEvent": (".ledger_models", "ContradictionEvent"),
    "MemoryAssertion": (".ledger_models", "MemoryAssertion"),
    "MemoryEpisode": (".ledger_models", "MemoryEpisode"),
    "MemoryEvent": (".ledger_models", "MemoryEvent"),
    "MemoryRelation": (".ledger_models", "MemoryRelation"),
    "ProfileFact": (".ledger_models", "ProfileFact"),
    "ProjectionStatus": (".ledger_models", "ProjectionStatus"),
    "ReinforcementEvent": (".ledger_models", "ReinforcementEvent"),
    "RetentionPolicy": (".ledger_models", "RetentionPolicy"),
    # Profile/retrieval/evaluation services.
    "ProfileService": (".profile_synthesis", "ProfileService"),
    "get_profile_service": (".profile_synthesis", "get_profile_service"),
    "HybridRetrievalRouter": (".retrieval", "HybridRetrievalRouter"),
    "get_retrieval_router": (".retrieval", "get_retrieval_router"),
    "MemoryEvalHarness": (".evaluation", "MemoryEvalHarness"),
    "get_eval_harness": (".evaluation", "get_eval_harness"),
    # Neuro-memory contracts/services.
    "ConsolidationDecision": (".neuro", "ConsolidationDecision"),
    "LessonArtifact": (".neuro", "LessonArtifact"),
    "MemoryActivationDecision": (".neuro", "MemoryActivationDecision"),
    "MemoryActivationMode": (".neuro", "MemoryActivationMode"),
    "MemoryCandidate": (".neuro", "MemoryCandidate"),
    "MemoryClass": (".neuro", "MemoryClass"),
    "ProcedureArtifact": (".neuro", "ProcedureArtifact"),
    # Cognitive service implementations.
    "LifecycleEvent": (".lifecycle", "LifecycleEvent"),
    "LifecycleHook": (".lifecycle", "LifecycleHook"),
    "MemoryLifecycle": (".lifecycle", "MemoryLifecycle"),
    "MemoryClaimStore": (".claims", "MemoryClaimStore"),
    "AssociationGraph": (".associative", "AssociationGraph"),
    "SpreadingActivation": (".associative", "SpreadingActivation"),
    "ReflectionEngine": (".reflection", "ReflectionEngine"),
    "SelfModelStore": (".self_model", "SelfModelStore"),
    "UserModelStore": (".user_model", "UserModelStore"),
    "RelationshipModelStore": (".relationship_model", "RelationshipModelStore"),
    "ProspectiveMemoryStore": (".prospective", "ProspectiveMemoryStore"),
    # CORE-SPLIT-2 recall authority and adapters.
    "DefaultRecallService": ("..recall", "DefaultRecallService"),
    "RecallManagerRecallAdapter": (".adapters", "RecallManagerRecallAdapter"),
    "RetrievalRouterRecallAdapter": (".adapters", "RetrievalRouterRecallAdapter"),
}


def __getattr__(name: str) -> Any:
    """Resolve compatibility/runtime exports only on explicit access.

    This is intentionally a package-boundary mechanism, not an orchestration
    path. It prevents cognitive contract imports from acquiring runtime or
    platform side effects while preserving historical package-root imports.
    """

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name, package=__name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "get_memory_manager",
    "MemoryRuntimeManager",
    "init_memory",
    "close",
    "recall_context",
    "update_memory",
    "get_metrics",
    "get_profile_service",
    "ProfileService",
    "get_retrieval_router",
    "HybridRetrievalRouter",
    "get_eval_harness",
    "MemoryEvalHarness",
    "MemoryEvent",
    "MemoryAssertion",
    "MemoryEpisode",
    "ProfileFact",
    "MemoryRelation",
    "ReinforcementEvent",
    "ContradictionEvent",
    "ProjectionStatus",
    "ConsentScope",
    "RetentionPolicy",
    "MemoryClass",
    "MemoryActivationMode",
    "MemoryActivationDecision",
    "MemoryCandidate",
    "ConsolidationDecision",
    "ProcedureArtifact",
    "LessonArtifact",
    # Cognitive architecture.
    "MemoryClaim",
    "ClaimStatus",
    "SalienceScore",
    "SelfModel",
    "UserModel",
    "RelationshipModel",
    "ProspectiveMemory",
    "MemoryLifecycleState",
    "RecallScoreComponents",
    "SaliencePolicy",
    "ForgettingPolicy",
    "ConsolidationPolicy",
    "RetrievalPolicy",
    "CognitiveMemoryType",
    "CognitiveMemoryEntry",
    "MemoryContext",
    "AssociativeActivation",
    "ReflectionCandidate",
    "MemoryLifecycle",
    "LifecycleHook",
    "LifecycleEvent",
    "MemoryClaimStore",
    "AssociationGraph",
    "SpreadingActivation",
    "ReflectionEngine",
    "SelfModelStore",
    "UserModelStore",
    "RelationshipModelStore",
    "ProspectiveMemoryStore",
    # CORE-SPLIT-2 recall authority.
    "DefaultRecallService",
    "RecallManagerRecallAdapter",
    "RetrievalRouterRecallAdapter",
]
