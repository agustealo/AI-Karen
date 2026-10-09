"""
IntelligenceRuntime contracts.

Defines the canonical data structures for intelligence analysis results,
signal provenance, and capability contracts. All NLP/ML inference flows
through these contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalSourceType(str, Enum):
    """Provenance source for an intelligence signal."""

    TRANSFORMER = "transformer"
    SPACY = "spacy"
    RULE = "rule"
    HEURISTIC = "heuristic"
    FALLBACK = "fallback"


class SignalType(str, Enum):
    """Type of intelligence signal."""

    INTENT = "intent"
    ENTITY = "entity"
    TOPIC = "topic"
    SENTIMENT = "sentiment"
    PREFERENCE = "preference"
    FORECAST = "forecast"
    BEHAVIOR_PATTERN = "behavior_pattern"
    EMBEDDING = "embedding"
    TASK_COMPLEXITY = "task_complexity"
    MEMORY_RELEVANCE = "memory_relevance"
    RISK = "risk"
    KEY_PHRASE = "key_phrase"


@dataclass
class IntelligenceSignal:
    """A single intelligence signal with full provenance."""

    signal_type: SignalType
    value: Any
    confidence: float = 0.0

    source_type: SignalSourceType = SignalSourceType.RULE
    source_id: str = ""
    model_id: str = ""
    model_version: str = ""

    fallback_used: bool = False
    latency_ms: float = 0.0

    feature_version: str = "v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    encoder_model: str = ""
    inference_method: str = ""


@dataclass(frozen=True, slots=True)
class SemanticInterpretation:
    """Model-independent meaning signal, not an authorization or memory fact.

    Unknown values must stay unknown. A recognized pattern is not equivalent
    to a calibrated intent probability, and evidence requests are advisory to
    CORTEX/RuntimePolicy, never permission grants.
    """

    intent_family: str = "unknown"
    requested_profile_attribute: str | None = None
    subject: str | None = None
    predicate: str | None = None
    object_text: str | None = None
    temporal_reference: str | None = None
    ambiguity: "TaskAmbiguity" = field(default_factory=lambda: TaskAmbiguity.UNKNOWN)
    candidate_interpretations: tuple[str, ...] = ()
    evidence_needs: tuple[str, ...] = ()
    confidence: float | None = None
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("semantic confidence must be in [0, 1]")
        if not self.intent_family.strip():
            raise ValueError("intent_family must not be empty")


@dataclass
class IntelligenceAnalysisResult:
    """Complete intelligence analysis result from IntelligenceRuntime."""

    intent: str = "general_assist"
    intent_confidence: float = 0.0

    entities: list[dict[str, Any]] = field(default_factory=list)
    key_phrases: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)

    embedding_ref: str | None = None
    semantic_features: dict[str, Any] = field(default_factory=dict)

    task_complexity: str = "simple"
    memory_relevance: float = 0.0

    topology_signals: dict[str, Any] = field(default_factory=dict)
    risk_signals: dict[str, Any] = field(default_factory=dict)
    capability_hints: dict[str, Any] = field(default_factory=dict)
    adaptive_signals: dict[str, Any] = field(default_factory=dict)

    signals: list[IntelligenceSignal] = field(default_factory=list)
    interpretation: SemanticInterpretation | None = None

    signal_provenance: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    degraded: bool = False


# ===========================
# Task Signature
# ===========================

class TaskComplexity(str, Enum):
    """Canonical task complexity levels."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    EXPERT = "expert"


class TaskAmbiguity(str, Enum):
    """Canonical task ambiguity levels."""

    CLEAR = "clear"
    MODERATE = "moderate"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class TaskRisk(str, Enum):
    """Canonical task risk levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TaskSignature:
    """Canonical task representation for adaptive intelligence.

    CORTEX produces this from raw user input. RuntimePolicy, MedusaRegistry,
    and CapabilityGraph consume it to decide execution topology, agent/model
    assignment, and skill selection.
    """

    intent: str = "general_assist"
    domains: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    semantic_embedding: list[float] | None = None

    complexity: TaskComplexity = TaskComplexity.SIMPLE
    ambiguity: TaskAmbiguity = TaskAmbiguity.CLEAR
    novelty: float = 0.0
    risk: TaskRisk = TaskRisk.LOW

    tool_requirements: list[str] = field(default_factory=list)
    reasoning_requirements: list[str] = field(default_factory=list)

    collaboration_value: float = 0.0
    verification_value: float = 0.0

    metadata: dict[str, Any] = field(default_factory=dict)
