"""
AI-Karen Learning Systems - Premium Production Implementation

The learning module provides enterprise-grade case-based reasoning and
experience replay capabilities without requiring model fine-tuning.

Key Features:
- Case-Memory Learning: Memento-style experience learning with semantic retrieval
- Dual-Stage Retrieval: Fast vector recall + cross-encoder reranking
- Admission Policy: Intelligent filtering based on reward and novelty
- Multi-Tenant Isolation: Secure tenant-specific case storage
- Observability: Comprehensive metrics and health monitoring
- Storage Integration: Postgres + Redis for optimal performance

Architecture:
- Case Types: Immutable dataclasses for type-safe case representation
- Case Store: Storage facade with multi-backend support
- Retriever: Semantic search with configurable ranking
- Admission Policy: Configurable quality gating
- Planner Hooks: Integration points for planning and execution
- Metrics: Real-time observability and alerting

Usage Example:
    from ai_karen_engine.learning import (
        CaseStore, CaseRetriever, AdmissionPolicy, PlannerHooks
    )

    # Initialize components
    store = CaseStore(pg, redis)
    retriever = CaseRetriever(store, embedder, reranker)
    policy = AdmissionPolicy(AdmissionConfig(min_reward=0.6))
    hooks = PlannerHooks(retriever, embedder, store, reward_adapters)

    # Use in planning
    context = hooks.pre_plan_context(tenant_id, task, tags)

    # Learn from execution
    hooks.on_run_complete(
        tenant_id=tenant_id,
        user_id=user_id,
        task_text=task,
        steps=steps,
        outcome_text=outcome,
        tags=tags,
        pointers=pointers
    )
"""

# Import all case_memory components
from ai_karen_engine.learning.case_memory import (
    # Core types
    Case,
    StepTrace,
    ToolIO,
    Reward,

    # Storage and retrieval
    CaseStore,
    CaseRetriever,
    RetrieveConfig,

    # Admission control
    AdmissionPolicy,
    AdmissionConfig,

    # Integration hooks
    PlannerHooks,
)

# Import metrics and observability
from ai_karen_engine.learning.case_memory.metrics import (
    CaseMemoryMetrics,
    CaseMemoryObserver,
    get_observer,
    initialize_observer,
)

__all__ = [
    # Core types
    "Case",
    "StepTrace",
    "ToolIO",
    "Reward",

    # Storage and retrieval
    "CaseStore",
    "CaseRetriever",
    "RetrieveConfig",

    # Admission control
    "AdmissionPolicy",
    "AdmissionConfig",

    # Integration hooks
    "PlannerHooks",

    # Observability
    "CaseMemoryMetrics",
    "CaseMemoryObserver",
    "get_observer",
    "initialize_observer",
]

# Version info
__version__ = "1.0.0"
__author__ = "AI-Karen Team"
__description__ = "Premium case-based learning system for AI-Karen"
