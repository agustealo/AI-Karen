"""
Preference drift detection for AI-Karen personalization.

Detects when previously reliable preferences stop matching recent evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..contracts import (
    DriftState,
    PreferenceRecord,
    PreferenceState,
)


class DriftDetector:
    """Detects concept drift in user preferences."""

    def __init__(self, watch_threshold: float = 0.3, drift_threshold: float = 0.5):
        self.watch_threshold = watch_threshold
        self.drift_threshold = drift_threshold
        self._history: Dict[str, List[Dict[str, Any]]] = {}

    def evaluate(self, record: PreferenceRecord) -> DriftState:
        history = self._history.get(record.preference_id, [])
        if not history:
            self._history[record.preference_id] = [self._snapshot(record)]
            return DriftState.UNKNOWN

        self._history[record.preference_id].append(self._snapshot(record))
        if len(self._history[record.preference_id]) > 50:
            self._history[record.preference_id] = self._history[record.preference_id][-50:]

        contradiction_rate = record.contradiction_count / max(1, record.evidence_count)
        recency_score = self._recency_score(record)
        correction_signals = record.metadata.get("recent_corrections", 0)

        drift_score = (
            0.4 * contradiction_rate
            + 0.3 * (1.0 - recency_score)
            + 0.3 * min(1.0, correction_signals / 5.0)
        )

        if drift_score >= self.drift_threshold:
            return DriftState.DRIFTING
        if drift_score >= self.watch_threshold:
            return DriftState.WATCH
        if record.state == PreferenceState.CONTRADICTED:
            return DriftState.CHANGED
        return DriftState.STABLE

    def _recency_score(self, record: PreferenceRecord) -> float:
        age = datetime.utcnow() - record.last_observed_at
        max_age = timedelta(days=30)
        return max(0.0, min(1.0, 1.0 - (age.total_seconds() / max_age.total_seconds())))

    def _snapshot(self, record: PreferenceRecord) -> Dict[str, Any]:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "state": record.state.value,
            "confidence": record.confidence,
            "evidence_count": record.evidence_count,
            "contradiction_count": record.contradiction_count,
        }


__all__ = ["DriftDetector"]
