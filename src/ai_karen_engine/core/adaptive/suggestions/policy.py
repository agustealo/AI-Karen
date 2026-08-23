"""Suggestion frequency and threshold policy.

Controls when suggestions are surfaced based on utility, confidence, and interruption cost.
"""

from __future__ import annotations

import logging

from ai_karen_engine.core.adaptive.contracts import SuggestionCandidate
from ai_karen_engine.core.adaptive.suggestions.dedupe import SuggestionDedupeStore

logger = logging.getLogger(__name__)


class SuggestionPolicy:
    """Policy for surfacing suggestions."""

    def __init__(
        self,
        dedupe_store: SuggestionDedupeStore | None = None,
        threshold: float = 0.6,
        max_per_request: int = 3,
        cooldown_seconds: int = 3600,
    ) -> None:
        self._dedupe_store = dedupe_store or SuggestionDedupeStore()
        self._threshold = threshold
        self._max_per_request = max_per_request
        self._cooldown_seconds = cooldown_seconds

    def should_surface(self, candidate: SuggestionCandidate) -> bool:
        """Determine if a suggestion should be surfaced."""
        if candidate.utility < self._threshold:
            return False
        if candidate.interruption_cost > 0.7:
            return False
        if self._dedupe_store.is_duplicate(candidate, self._cooldown_seconds):
            return False
        dismissal_count = self._dedupe_store.dismissal_count(
            candidate.dedupe_key or candidate.suggestion_type
        )
        return not dismissal_count >= 3

    def record_surface(self, candidate: SuggestionCandidate) -> None:
        self._dedupe_store.record(candidate)

    def record_dismissal(self, candidate: SuggestionCandidate) -> None:
        self._dedupe_store.record_dismissal(candidate)

    def update_threshold(self, threshold: float) -> None:
        self._threshold = max(0.0, min(1.0, threshold))
