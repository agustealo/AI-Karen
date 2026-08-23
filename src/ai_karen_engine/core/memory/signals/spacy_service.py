"""
Compatibility shim for core.memory.signals.spacy_service.

Canonical implementation now lives under core.intelligence.linguistic.spacy_analyzer.
This module preserves the legacy SpacyService API for external consumers during
the sprint transition.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ai_karen_engine.core.intelligence.linguistic.contracts import (
    EntityExtractionResult,
    KeyPhraseResult,
    ParsedMessage,
)
from ai_karen_engine.core.intelligence.linguistic.spacy_analyzer import SpacyAnalyzer
from ai_karen_engine.core.intelligence.linguistic.spacy_config import SpacyConfig

logger = logging.getLogger(__name__)

try:
    from cachetools import TTLCache
except ImportError:
    class TTLCache(dict):
        def __init__(self, maxsize: int, ttl: float):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._expires: dict[Any, float] = {}

        def _purge_expired(self) -> None:
            now = time.time()
            expired = [key for key, deadline in self._expires.items() if deadline <= now]
            for key in expired:
                self._expires.pop(key, None)
                super().pop(key, None)

        def __contains__(self, key) -> bool:
            self._purge_expired()
            return super().__contains__(key)

        def __getitem__(self, key):
            self._purge_expired()
            return super().__getitem__(key)

        def get(self, key, default=None):
            self._purge_expired()
            return super().get(key, default)

        def __setitem__(self, key, value) -> None:
            self._purge_expired()
            if key not in self and len(self) >= self.maxsize:
                oldest_key = min(self._expires, key=self._expires.get)
                self._expires.pop(oldest_key, None)
                super().pop(oldest_key, None)
            self._expires[key] = time.time() + self.ttl
            super().__setitem__(key, value)

        def __len__(self) -> int:
            self._purge_expired()
            return super().__len__()


class TextNormalizationResult:
    def __init__(self, normalized_text: str, original_text: str, normalizations_applied: list[str], processing_time: float, used_fallback: bool):
        self.normalized_text = normalized_text
        self.original_text = original_text
        self.normalizations_applied = normalizations_applied
        self.processing_time = processing_time
        self.used_fallback = used_fallback


class StructuredAnalysisResult:
    def __init__(self, structure: dict[str, Any], key_information: dict[str, Any], relationships: list[dict[str, Any]], processing_time: float, used_fallback: bool):
        self.structure = structure
        self.key_information = key_information
        self.relationships = relationships
        self.processing_time = processing_time
        self.used_fallback = used_fallback


class SpacyHealthStatus:
    def __init__(self, is_healthy: bool, model_loaded: bool, fallback_mode: bool, cache_size: int, cache_hit_rate: float, avg_processing_time: float, error_count: int, last_error: str | None = None):
        self.is_healthy = is_healthy
        self.model_loaded = model_loaded
        self.fallback_mode = fallback_mode
        self.cache_size = cache_size
        self.cache_hit_rate = cache_hit_rate
        self.avg_processing_time = avg_processing_time
        self.error_count = error_count
        self.last_error = last_error


class SpacyService:
    def __init__(self, config: SpacyConfig | None = None):
        self.config = config or SpacyConfig()
        self._analyzer = SpacyAnalyzer(self.config)
        self.fallback_mode = self._analyzer.fallback_mode
        self.cache = self._analyzer.cache

    async def parse_message(self, text: str) -> ParsedMessage:
        return await self._analyzer.parse(text)

    async def extract_entities(self, text: str) -> list[tuple[str, str]]:
        result = await self._analyzer.extract_entities(text)
        return [(e.get("text", ""), e.get("label", "")) for e in result.entities]

    async def extract_entities_enhanced(self, text: str) -> EntityExtractionResult:
        return await self._analyzer.extract_entities(text)

    async def identify_key_phrases(self, text: str, max_phrases: int = 10, min_phrase_length: int = 2) -> KeyPhraseResult:
        return await self._analyzer.extract_key_phrases(text, max_phrases, min_phrase_length)

    async def normalize_text(self, text: str, normalization_options: dict[str, bool] | None = None) -> TextNormalizationResult:
        parsed = await self._analyzer.parse(text)
        options = normalization_options or {"lemmatize": True, "lowercase": True, "remove_punctuation": False, "remove_stopwords": False, "remove_whitespace": True}
        normalized_tokens = []
        normalizations_applied = []
        for token, lemma, pos in zip(parsed.tokens, parsed.lemmas, [p[1] for p in parsed.pos_tags]):
            normalized = token
            if options.get("lemmatize") and not token.ispunct():
                normalized = lemma
                normalizations_applied.append("lemmatize")
            if options.get("lowercase"):
                normalized = normalized.lower()
                if "lowercase" not in normalizations_applied:
                    normalizations_applied.append("lowercase")
            if options.get("remove_punctuation") and pos == "PUNCT":
                continue
            if options.get("remove_stopwords"):
                continue
            normalized_tokens.append(normalized)
        normalized_text = " ".join(normalized_tokens)
        if options.get("remove_whitespace"):
            normalized_text = " ".join(normalized_text.split())
            if "remove_whitespace" not in normalizations_applied:
                normalizations_applied.append("remove_whitespace")
        return TextNormalizationResult(normalized_text, text, normalizations_applied, 0.0, parsed.used_fallback)

    async def analyze_structure(self, text: str) -> StructuredAnalysisResult:
        parsed = await self._analyzer.parse(text)
        structure = {
            "sentence_count": len(parsed.sentences),
            "token_count": len(parsed.tokens),
            "avg_sentence_length": len(parsed.tokens) / len(parsed.sentences) if parsed.sentences else 0,
            "complexity_score": 0.0,
        }
        key_information = {
            "main_entities": [e[0] for e in parsed.entities[:5]],
            "main_verbs": [],
            "main_nouns": [],
        }
        relationships = []
        return StructuredAnalysisResult(structure, key_information, relationships, 0.0, parsed.used_fallback)

    async def extract_facts(self, text: str) -> list[dict[str, Any]]:
        parsed = await self._analyzer.parse(text)
        facts = []
        for entity_text, entity_label in parsed.entities:
            facts.append({"type": "entity", "entity": entity_text, "label": entity_label, "confidence": "high"})
        if not parsed.used_fallback:
            for dep in parsed.dependencies:
                if dep["dep"] in ["nsubj", "dobj", "pobj"] and dep["head"] != "ROOT":
                    facts.append({"type": "relationship", "subject": dep["text"], "relation": dep["dep"], "object": dep["head"], "confidence": "medium"})
        return facts

    async def get_linguistic_features(self, text: str) -> dict[str, Any]:
        parsed = await self._analyzer.parse(text)
        pos_counts = {}
        for _, pos in parsed.pos_tags:
            pos_counts[pos] = pos_counts.get(pos, 0) + 1
        dep_counts = {}
        for dep in parsed.dependencies:
            dep_type = dep["dep"]
            dep_counts[dep_type] = dep_counts.get(dep_type, 0) + 1
        return {
            "token_count": len(parsed.tokens),
            "sentence_count": len(parsed.sentences),
            "entity_count": len(parsed.entities),
            "noun_phrase_count": len(parsed.noun_phrases),
            "pos_distribution": pos_counts,
            "dependency_distribution": dep_counts,
            "avg_sentence_length": len(parsed.tokens) / len(parsed.sentences) if parsed.sentences else 0,
            "language": parsed.language,
            "used_fallback": parsed.used_fallback,
        }

    async def reload_model(self, new_model_name: str | None = None):
        if new_model_name:
            self.config.model_name = new_model_name
        self._analyzer = SpacyAnalyzer(self.config)
        self.fallback_mode = self._analyzer.fallback_mode

    def get_health_status(self) -> SpacyHealthStatus:
        health = asyncio.get_event_loop().run_until_complete(self._analyzer.health())
        return SpacyHealthStatus(
            is_healthy=health.get("status") != "error",
            model_loaded=health.get("model_loaded", False),
            fallback_mode=health.get("fallback_mode", False),
            cache_size=health.get("cache_size", 0),
            cache_hit_rate=health.get("cache_hit_rate", 0.0),
            avg_processing_time=health.get("avg_processing_time", 0.0),
            error_count=health.get("error_count", 0),
            last_error=health.get("last_error"),
        )

    def clear_cache(self) -> None:
        self._analyzer.clear_cache()

    def reset_metrics(self) -> None:
        self._analyzer.reset_metrics()

    async def enhance_memory_retrieval(self, query_text: str, memory_candidates: list[str]) -> dict[str, Any]:
        return {"enhanced_scores": {}, "analysis": {}, "processing_time": 0.0, "used_fallback": True}


_spacy_service: SpacyService | None = None


def get_spacy_service() -> SpacyService:
    global _spacy_service
    if _spacy_service is None:
        _spacy_service = SpacyService()
    return _spacy_service


def reset_spacy_service() -> None:
    global _spacy_service
    _spacy_service = None
