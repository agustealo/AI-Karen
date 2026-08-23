from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntelligenceFeatures:
    semantic_embedding: list[float] | None = None
    token_count: int = 0
    sentence_count: int = 0
    entity_count: int = 0
    entity_labels: list[str] = field(default_factory=list)
    key_phrases: list[str] = field(default_factory=list)
    linguistic_features: dict[str, Any] = field(default_factory=dict)
    syntax_features: dict[str, Any] = field(default_factory=dict)
    temporal_features: dict[str, Any] = field(default_factory=dict)
    request_features: dict[str, Any] = field(default_factory=dict)
    conversation_features: dict[str, Any] = field(default_factory=dict)
    feature_version: str = "v1"
    text: str = ""
