"""
Core Memory Domain for AI Karen Engine.

Runtime authority note:
- `ai_karen_engine.core.memory` is the single live runtime memory authority.
- Legacy `core.neuro_vault` remains migration/compatibility scope only.

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

from .ledger_models import (
    ConsentScope,
    ContradictionEvent,
    MemoryAssertion,
    MemoryEpisode,
    MemoryEvent,
    MemoryRelation,
    ProfileFact,
    ProjectionStatus,
    ReinforcementEvent,
    RetentionPolicy,
)
from .memory_runtime_manager import (
    MemoryRuntimeManager,
    close,
    get_memory_manager,
    get_metrics,
    init_memory,
    recall_context,
    update_memory,
)

try:
    from .profile_synthesis import ProfileService, get_profile_service
except ImportError:
    get_profile_service = None
    ProfileService = None

try:
    from .retrieval import HybridRetrievalRouter, get_retrieval_router
except ImportError:
    get_retrieval_router = None
    HybridRetrievalRouter = None

get_eval_harness = None
MemoryEvalHarness = None

try:
    from .evaluation import MemoryEvalHarness as _MemoryEvalHarness
    from .evaluation import get_eval_harness as _get_eval_harness
except ImportError:
    _get_eval_harness = None
    _MemoryEvalHarness = None
else:
    get_eval_harness = _get_eval_harness
    MemoryEvalHarness = _MemoryEvalHarness

try:
    from .neuro import (
        ConsolidationDecision,
        LessonArtifact,
        MemoryActivationDecision,
        MemoryActivationMode,
        MemoryCandidate,
        MemoryClass,
        ProcedureArtifact,
    )
except ImportError:
    MemoryClass = None
    MemoryActivationMode = None
    MemoryActivationDecision = None
    MemoryCandidate = None
    ConsolidationDecision = None
    ProcedureArtifact = None
    LessonArtifact = None

# Cognitive architecture exports
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

try:
    from .lifecycle import LifecycleEvent, LifecycleHook, MemoryLifecycle
except ImportError:
    MemoryLifecycle = None
    LifecycleHook = None
    LifecycleEvent = None

try:
    from .claims import MemoryClaimStore
except ImportError:
    MemoryClaimStore = None

try:
    from .associative import AssociationGraph, SpreadingActivation
except ImportError:
    AssociationGraph = None
    SpreadingActivation = None

try:
    from .reflection import ReflectionEngine
except ImportError:
    ReflectionEngine = None

try:
    from .self_model import SelfModelStore
except ImportError:
    SelfModelStore = None

try:
    from .user_model import UserModelStore
except ImportError:
    UserModelStore = None

try:
    from .relationship_model import RelationshipModelStore
except ImportError:
    RelationshipModelStore = None

try:
    from .prospective import ProspectiveMemoryStore
except ImportError:
    ProspectiveMemoryStore = None

# CORE-SPLIT-2 recall authority
try:
    from ..recall import DefaultRecallService
except ImportError:
    DefaultRecallService = None

try:
    from .adapters import (
        RecallManagerRecallAdapter,
        RetrievalRouterRecallAdapter,
    )
except ImportError:
    RecallManagerRecallAdapter = None
    RetrievalRouterRecallAdapter = None

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
    # Cognitive architecture
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
    # CORE-SPLIT-2 recall authority
    "DefaultRecallService",
    "RecallManagerRecallAdapter",
    "RetrievalRouterRecallAdapter",
]
