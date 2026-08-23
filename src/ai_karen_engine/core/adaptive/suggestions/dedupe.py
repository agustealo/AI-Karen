"""Suggestion deduplication.

Prevents repeated suggestions within cooldown windows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ai_karen_engine.core.adaptive.suggestions.contracts import SuggestionCandidate

logger = logging.getLogger(__name__)


class SuggestionDedupeStore:
    """Tracks suggestion dedupe keys and cooldowns."""

    def __init__(self) -> None:
        self._recent_keys: dict[str, str] = {}
        self._dismissed_classes: dict[str, int] = {}

    def is_duplicate(self, candidate: SuggestionCandidate, cooldown_seconds: int = 3600) -> bool:
        """Check if a suggestion is a duplicate within cooldown."""
        key = candidate.dedupe_key or candidate.subject
        last_seen = self._recent_keys.get(key)
        if last_seen is None:
            return False
        try:
            last_dt = datetime.fromisoformat(last_seen)
            now = datetime.now(timezone.utc)
            if (now - last_dt).total_seconds() < cooldown_seconds:
                return True
        except ValueError:
            pass
        return False

    def record(self, candidate: SuggestionCandidate) -> None:
        key = candidate.dedupe_key or candidate.subject
        self._recent_keys[key] = datetime.now(timezone.utc).isoformat()

    def record_dismissal(self, candidate: SuggestionCandidate) -> None:
        key = candidate.dedupe_key or candidate.suggestion_type
        self._dismissed_classes[key] = self._dismissed_classes.get(key, 0) + 1

    def dismissal_count(self, dedupe_key: str) -> int:
        return self._dismissed_classes.get(dedupe_key, 0)

    def clear(self) -> None:
        self._recent_keys.clear()
        self._dismissed_classes.clear()
