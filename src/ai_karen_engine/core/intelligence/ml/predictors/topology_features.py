from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures

logger = logging.getLogger(__name__)

FEATURE_VERSION = "topology_features_v1"

FEATURE_ORDER = [
    "token_count",
    "sentence_count",
    "entity_count",
    "intent_confidence",
    "complexity_score",
    "ambiguity_score",
    "memory_relevance_score",
    "capability_count",
    "tool_requirement_count",
    "multiple_actions",
    "dependency_chain",
    "external_lookup",
    "code_execution",
    "filesystem_operation",
    "parallelizable",
    "requires_followup",
    "risk_score",
    "web_search",
    "code_execution_hint",
    "filesystem_read",
    "filesystem_write",
    "tool_use",
    "deep_reasoning",
    "structured_output",
]


@dataclass
class TopologyFeatureVector:
    feature_version: str = FEATURE_VERSION
    features: dict[str, float | int | bool | str] = field(default_factory=dict)

    token_count: int = 0
    sentence_count: int = 0
    entity_count: int = 0

    intent_confidence: float = 0.0
    complexity_score: float = 0.0
    ambiguity_score: float = 0.0
    memory_relevance_score: float = 0.0

    capability_count: int = 0
    tool_requirement_count: int = 0

    multiple_actions: bool = False
    dependency_chain: bool = False
    external_lookup: bool = False
    code_execution: bool = False
    filesystem_operation: bool = False
    parallelizable: bool = False
    requires_followup: bool = False

    risk_score: float = 0.0

    web_search: bool = False
    code_execution_hint: bool = False
    filesystem_read: bool = False
    filesystem_write: bool = False
    tool_use: bool = False
    deep_reasoning: bool = False
    structured_output: bool = False


def build_topology_feature_vector(features: IntelligenceFeatures) -> TopologyFeatureVector:
    capability_hints = features.request_features.get("capability_hints", {})
    topology_signals = features.request_features.get("topology_signals", {})

    vector = TopologyFeatureVector(
        token_count=features.token_count,
        sentence_count=features.sentence_count,
        entity_count=features.entity_count,
        intent_confidence=features.request_features.get("intent_confidence", 0.0),
        complexity_score=_score_from_label(features.request_features.get("complexity", "simple")),
        ambiguity_score=_score_from_label(features.request_features.get("ambiguity", "clear")),
        memory_relevance_score=features.request_features.get("memory_relevance", 0.0),
        capability_count=len(features.request_features.get("capability_candidates", [])),
        tool_requirement_count=len(features.request_features.get("tool_requirements", [])),
        multiple_actions=topology_signals.get("multiple_actions", False),
        dependency_chain=topology_signals.get("dependency_chain", False),
        external_lookup=topology_signals.get("external_lookup", False),
        code_execution=topology_signals.get("code_execution", False),
        filesystem_operation=topology_signals.get("filesystem_operation", False),
        parallelizable=topology_signals.get("parallelizable", False),
        requires_followup=topology_signals.get("requires_followup", False),
        risk_score=features.request_features.get("risk_score", 0.0),
        web_search=bool(capability_hints.get("web_search", False)),
        code_execution_hint=bool(capability_hints.get("code_execution", False)),
        filesystem_read=bool(capability_hints.get("filesystem_read", False)),
        filesystem_write=bool(capability_hints.get("filesystem_write", False)),
        tool_use=bool(capability_hints.get("tool_use", False)),
        deep_reasoning=bool(capability_hints.get("deep_reasoning", False)),
        structured_output=bool(capability_hints.get("structured_output", False)),
    )

    for key in FEATURE_ORDER:
        vector.features[key] = getattr(vector, key)

    return vector


def _score_from_label(label: str) -> float:
    mapping = {"simple": 0.0, "clear": 0.0, "low": 0.0, "moderate": 0.5, "medium": 0.5, "complex": 1.0, "high": 1.0, "expert": 1.0, "critical": 1.0, "ambiguous": 1.0}
    return mapping.get(label, 0.0)


def topology_feature_vector_to_dict(vector: TopologyFeatureVector) -> dict[str, float | int | bool | str]:
    return dict(vector.features)
