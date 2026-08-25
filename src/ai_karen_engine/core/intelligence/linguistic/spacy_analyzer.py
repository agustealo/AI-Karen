from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Any

from ai_karen_engine.core.intelligence.linguistic.contracts import (
    EntityExtractionResult,
    KeyPhraseResult,
    LinguisticHealthStatus,
    LinguisticMetadata,
    ParsedMessage,
)
from ai_karen_engine.core.intelligence.linguistic.spacy_config import SpacyConfig

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

logger = logging.getLogger(__name__)

try:
    import spacy
    SPACY_AVAILABLE = True
except Exception:
    spacy = None
    SPACY_AVAILABLE = False


class SpacyAnalyzer:
    def __init__(self, config: SpacyConfig | None = None) -> None:
        self.config = config or SpacyConfig()
        self.nlp = None
        self.fallback_mode = False
        self.cache = TTLCache(maxsize=self.config.cache_size, ttl=self.config.cache_ttl)
        self.lock = threading.RLock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._processing_times: list[float] = []
        self._error_count = 0
        self._last_error: str | None = None
        self._initialize()

    def _initialize(self) -> None:
        if not SPACY_AVAILABLE:
            logger.warning("spaCy not available, using fallback mode")
            self.fallback_mode = True
            return

        local_model_root = Path(getattr(self.config, "local_model_root", "models/spacy"))
        local_model_path = local_model_root / self.config.model_name

        def _try_load_local(path: Path) -> bool:
            if path.exists():
                try:
                    self.nlp = spacy.load(path, disable=self.config.disabled_components)
                    logger.info("Loaded spaCy model from local path: %s", path)
                    return True
                except (OSError, ValueError) as exc:
                    logger.warning("Failed to load local spaCy model from %s: %s", path, exc)
            return False

        if not _try_load_local(local_model_path):
            try:
                self.nlp = spacy.load(self.config.model_name, disable=self.config.disabled_components)
            except OSError:
                if self.config.download_missing:
                    try:
                        from spacy.cli import download
                        download(self.config.model_name)
                        self.nlp = spacy.load(self.config.model_name, disable=self.config.disabled_components)
                    except Exception as exc:
                        logger.warning("Unable to provision spaCy model %s: %s", self.config.model_name, exc)
                        self.nlp = None
            if self.nlp is not None and local_model_root:
                try:
                    local_model_root.mkdir(parents=True, exist_ok=True)
                    self.nlp.to_disk(local_model_path)
                    logger.info("Saved spaCy model to local path: %s", local_model_path)
                except OSError as exc:
                    logger.warning("Failed to save spaCy model to %s: %s", local_model_path, exc)

        if self.nlp is None:
            self.fallback_mode = True

    async def parse(self, text: str) -> ParsedMessage:
        if not text or not text.strip():
            return ParsedMessage(used_fallback=True)
        cache_key = self._get_cache_key(text)
        with self.lock:
            if cache_key in self.cache:
                self._cache_hits += 1
                return self.cache[cache_key]
            self._cache_misses += 1

        start = time.time()
        try:
            if self.fallback_mode or not self.nlp:
                result = await self._fallback_parse(text)
            else:
                result = await self._spacy_parse(text)
            result.processing_time = time.time() - start
            with self.lock:
                self._processing_times.append(result.processing_time)
                if len(self._processing_times) > 1000:
                    self._processing_times = self._processing_times[-1000:]
                self.cache[cache_key] = result
            return result
        except Exception as exc:
            logger.error("Parse failed: %s", exc)
            self._error_count += 1
            self._last_error = str(exc)
            if not self.fallback_mode and self.config.enable_fallback:
                result = await self._fallback_parse(text)
                result.processing_time = time.time() - start
                return result
            raise

    async def _spacy_parse(self, text: str) -> ParsedMessage:
        loop = asyncio.get_event_loop()
        doc = await loop.run_in_executor(None, self.nlp, text)
        dependencies = []
        for token in doc:
            dependencies.append({
                "text": token.text,
                "lemma": token.lemma_,
                "pos": token.pos_,
                "tag": token.tag_,
                "dep": token.dep_,
                "head": token.head.text if token.head != token else "ROOT",
                "head_pos": token.head.pos_ if token.head != token else "ROOT",
                "children": [child.text for child in token.children],
            })
        return ParsedMessage(
            tokens=[t.text for t in doc],
            lemmas=[t.lemma_ for t in doc],
            entities=[(e.text, e.label_) for e in doc.ents],
            pos_tags=[(t.text, t.pos_) for t in doc],
            noun_phrases=[c.text for c in doc.noun_chunks],
            sentences=[s.text.strip() for s in doc.sents],
            dependencies=dependencies,
            language=doc.lang_,
            used_fallback=False,
        )

    async def _fallback_parse(self, text: str) -> ParsedMessage:
        tokens = text.split()
        sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
        dependencies = []
        for i, token in enumerate(tokens):
            dependencies.append({
                "text": token,
                "lemma": token.lower(),
                "pos": "UNKNOWN",
                "tag": "UNKNOWN",
                "dep": "UNKNOWN",
                "head": "ROOT" if i == 0 else tokens[0],
                "head_pos": "ROOT" if i == 0 else "UNKNOWN",
                "children": [],
            })
        return ParsedMessage(
            tokens=tokens,
            lemmas=[t.lower() for t in tokens],
            entities=[],
            pos_tags=[],
            noun_phrases=sentences,
            sentences=sentences,
            dependencies=dependencies,
            used_fallback=True,
        )

    async def extract_entities(self, text: str) -> EntityExtractionResult:
        parsed = await self.parse(text)
        entities = [{"text": etext, "label": elabel} for etext, elabel in parsed.entities]
        return EntityExtractionResult(
            entities=entities,
            processing_time=parsed.processing_time,
            used_fallback=parsed.used_fallback,
        )

    async def extract_key_phrases(self, text: str, max_phrases: int = 10, min_phrase_length: int = 2) -> KeyPhraseResult:
        parsed = await self.parse(text)
        key_phrases = parsed.noun_phrases[:max_phrases]
        phrase_scores = {p: min(len(p.split()) * 0.2, 1.0) for p in key_phrases}
        phrase_types = {p: "noun_phrase" for p in key_phrases}
        return KeyPhraseResult(
            key_phrases=key_phrases,
            phrase_scores=phrase_scores,
            processing_time=parsed.processing_time,
            used_fallback=parsed.used_fallback,
            phrase_types=phrase_types,
        )

    async def segment_sentences(self, text: str) -> list[str]:
        parsed = await self.parse(text)
        return parsed.sentences

    async def get_syntax(self, text: str) -> list[dict[str, Any]]:
        parsed = await self.parse(text)
        return parsed.dependencies

    async def get_language(self, text: str) -> str:
        parsed = await self.parse(text)
        return parsed.language

    async def health(self) -> dict[str, Any]:
        with self.lock:
            cache_total = self._cache_hits + self._cache_misses
            cache_hit_rate = self._cache_hits / cache_total if cache_total > 0 else 0.0
            avg_processing_time = sum(self._processing_times) / len(self._processing_times) if self._processing_times else 0.0
            status = LinguisticHealthStatus.DEGRADED.value if self.fallback_mode else LinguisticHealthStatus.READY.value
            return {
                "status": status,
                "model_loaded": self.nlp is not None,
                "fallback_mode": self.fallback_mode,
                "cache_size": len(self.cache),
                "cache_hit_rate": cache_hit_rate,
                "avg_processing_time": avg_processing_time,
                "error_count": self._error_count,
                "last_error": self._last_error,
            }

    async def metadata(self) -> LinguisticMetadata:
        return LinguisticMetadata(
            model_id=self.config.model_name,
            model_version="current",
            language="en",
            fallback_used=self.fallback_mode,
        )

    def _get_cache_key(self, text: str) -> str:
        return f"spacy:{hashlib.md5(text.encode()).hexdigest()}"

    def clear_cache(self) -> None:
        with self.lock:
            self.cache.clear()

    def reset_metrics(self) -> None:
        with self.lock:
            self._cache_hits = 0
            self._cache_misses = 0
            self._processing_times = []
            self._error_count = 0
            self._last_error = None
