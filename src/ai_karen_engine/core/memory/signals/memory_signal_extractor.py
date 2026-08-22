"""
Memory Signal Extractor.

Consumes canonical ``SpacyService`` parsed output and applies memory-specific
semantic rules to produce ``MemorySignal`` candidates.

This replaces the duplicate ``SpacyExtractionService``, which previously
loaded its own spaCy model independently of the canonical adapter.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .signal_models import MemorySignal
from .spacy_service import SpacyService, ParsedMessage

logger = logging.getLogger(__name__)

_PREFERENCE_LEMMAS = {"prefer", "like", "want", "need", "require"}
_PREFERENCE_SOURCE = "spacy_dep"


class MemorySignalExtractor:
    """Transform spaCy parsed output into memory signal candidates."""

    def __init__(self, spacy_service: Optional[SpacyService] = None):
        self.spacy_service = spacy_service or SpacyService()

    async def extract(self, text: str) -> List[MemorySignal]:
        """Extract memory signals from text using canonical spaCy parsing."""
        if not text or not text.strip():
            return []

        parsed = await self.spacy_service.parse_message(text)
        signals: List[MemorySignal] = []

        if parsed.entities:
            signals.append(
                MemorySignal(
                    text=text,
                    signal_type="entity",
                    confidence=0.8,
                    entities=parsed.entities,
                    scope="user",
                    metadata={"source": "spacy_ner"},
                )
            )

        signals.extend(self._extract_preferences(parsed))

        return signals

    def _extract_preferences(self, parsed: ParsedMessage) -> List[MemorySignal]:
        """Detect preference and directive cues from dependency parsing."""
        signals = []
        seen = set()

        for dep in parsed.dependencies:
            if dep.get("pos") != "VERB":
                continue

            lemma = dep.get("lemma", "")
            if lemma not in _PREFERENCE_LEMMAS:
                continue

            token_text = dep.get("text", "")
            children = dep.get("children", [])
            clause = " ".join([token_text] + children).strip()
            if not clause:
                continue

            key = (clause, _PREFERENCE_SOURCE)
            if key in seen:
                continue
            seen.add(key)

            signals.append(
                MemorySignal(
                    text=clause,
                    signal_type="preference",
                    confidence=0.75,
                    scope="user",
                    metadata={"source": _PREFERENCE_SOURCE},
                )
            )

        return signals
