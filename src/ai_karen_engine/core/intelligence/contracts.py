"""
IntelligenceRuntime contracts.

Defines the canonical data structures for intelligence analysis results,
signal provenance, and capability contracts. All NLP/ML inference flows
through these contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
    metadata: Dict[str, Any] = field(default_factory=dict)

    encoder_model: str = ""
    inference_method: str = ""


@dataclass
class IntelligenceAnalysisResult:
    """Complete intelligence analysis result from IntelligenceRuntime."""

    intent: str = "general_assist"
    intent_confidence: float = 0.0

    entities: List[Dict[str, Any]] = field(default_factory=list)
    key_phrases: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)

    embedding_ref: Optional[str] = None
    semantic_features: Dict[str, Any] = field(default_factory=dict)

    task_complexity: str = "simple"
    memory_relevance: float = 0.0

    topology_signals: Dict[str, Any] = field(default_factory=dict)
    risk_signals: Dict[str, Any] = field(default_factory=dict)
    capability_hints: Dict[str, Any] = field(default_factory=dict)

    signals: List[IntelligenceSignal] = field(default_factory=list)

    signal_provenance: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    degraded: bool = False
