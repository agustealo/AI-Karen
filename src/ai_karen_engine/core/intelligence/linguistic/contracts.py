from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LinguisticHealthStatus(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class LinguisticMetadata:
    model_id: str = ""
    model_version: str = ""
    language: str = "en"
    fallback_used: bool = False


@dataclass
class ParsedMessage:
    tokens: list[str] = field(default_factory=list)
    lemmas: list[str] = field(default_factory=list)
    entities: list[tuple[str, str]] = field(default_factory=list)
    pos_tags: list[tuple[str, str]] = field(default_factory=list)
    noun_phrases: list[str] = field(default_factory=list)
    sentences: list[str] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    language: str = "en"
    processing_time: float = 0.0
    used_fallback: bool = False


@dataclass
class EntityExtractionResult:
    entities: list[dict[str, Any]] = field(default_factory=list)
    processing_time: float = 0.0
    used_fallback: bool = False
    confidence_scores: dict[str, float] = field(default_factory=dict)
    entity_relationships: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class KeyPhraseResult:
    key_phrases: list[str] = field(default_factory=list)
    phrase_scores: dict[str, float] = field(default_factory=dict)
    processing_time: float = 0.0
    used_fallback: bool = False
    phrase_types: dict[str, str] = field(default_factory=dict)


@dataclass
class LinguisticAnalysisResult:
    parsed: ParsedMessage
    entities: EntityExtractionResult
    key_phrases: KeyPhraseResult
    metadata: LinguisticMetadata
    latency_ms: float = 0.0
    degraded: bool = False


class LinguisticAnalyzer:
    async def parse(self, text: str) -> ParsedMessage: ...
    async def extract_entities(self, text: str) -> EntityExtractionResult: ...
    async def extract_key_phrases(self, text: str, max_phrases: int = 10, min_phrase_length: int = 2) -> KeyPhraseResult: ...
    async def segment_sentences(self, text: str) -> list[str]: ...
    async def get_syntax(self, text: str) -> list[dict[str, Any]]: ...
    async def get_language(self, text: str) -> str: ...
    async def health(self) -> dict[str, Any]: ...
    async def metadata(self) -> LinguisticMetadata: ...
