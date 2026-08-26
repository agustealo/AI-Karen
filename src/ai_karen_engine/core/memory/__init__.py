"""Canonical AI KAREN memory-domain facade.

`core.memory` owns the memory domain. NeuroRecall owns production recall
strategy; NeuroVault is the governed durability boundary. Runtime/platform
implementations remain lazy so importing cognitive contracts has no persistence
or provider side effects.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

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


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Runtime authority.
    "MemoryRuntimeManager": (".memory_runtime_manager", "MemoryRuntimeManager"),
    "get_memory_manager": (".memory_runtime_manager", "get_memory_manager"),
    "init_memory": (".memory_runtime_manager", "init_memory"),
    "close": (".memory_runtime_manager", "close"),
    "recall_context": (".memory_runtime_manager", "recall_context"),
    "update_memory": (".memory_runtime_manager", "update_memory"),
    "get_metrics": (".memory_runtime_manager", "get_metrics"),
    # Canonical recall and governed durability contracts.
    "NeuroRecall": (".retrieval", "NeuroRecall"),
    "RecallRequest": (".retrieval", "RecallRequest"),
    "RecallResult": (".retrieval", "RecallResult"),
    "RecallScopeError": (".retrieval", "RecallScopeError"),
    "VaultContext": (".protocols", "VaultContext"),
    "VaultPort": (".protocols", "VaultPort"),
    "VaultWriteReceipt": (".protocols", "VaultWriteReceipt"),
    # Ledger compatibility.
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
    # Cognitive implementations.
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
}


def __getattr__(name: str) -> Any:
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
    "NeuroRecall",
    "RecallRequest",
    "RecallResult",
    "RecallScopeError",
    "VaultContext",
    "VaultPort",
    "VaultWriteReceipt",
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
]
