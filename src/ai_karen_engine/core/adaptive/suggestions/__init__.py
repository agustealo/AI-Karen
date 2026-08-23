"""Adaptive suggestions."""

from __future__ import annotations

from ai_karen_engine.core.adaptive.suggestions.contracts import (
    SuggestionCandidate,
    SuggestionFeedbackType,
    SuggestionRecord,
)
from ai_karen_engine.core.adaptive.suggestions.dedupe import SuggestionDedupeStore
from ai_karen_engine.core.adaptive.suggestions.engine import SuggestionEngine
from ai_karen_engine.core.adaptive.suggestions.policy import SuggestionPolicy

__all__ = [
    "SuggestionCandidate",
    "SuggestionDedupeStore",
    "SuggestionEngine",
    "SuggestionFeedbackType",
    "SuggestionPolicy",
    "SuggestionRecord",
]
