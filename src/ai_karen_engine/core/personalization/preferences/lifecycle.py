"""
Preference lifecycle management for AI-Karen personalization.

Handles state transitions, promotion, decay, and retirement of preferences.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from ..contracts import (
    PreferenceContradiction,
    PreferenceEvidence,
    PreferenceRecord,
    PreferenceState,
    PreferenceStability,
)
from .catalog import PreferenceCatalog


class PreferenceLifecycle:
    """Manages preference lifecycle state transitions."""

    @staticmethod
    def promote(record: PreferenceRecord, new_confidence: float) -> PreferenceRecord:
        thresholds = PreferenceCatalog.get_promotion_threshold(record.stability.value)
        if (record.evidence_count >= thresholds["min_evidence"]
                and new_confidence >= thresholds["min_confidence"]):
            if record.state == PreferenceState.TENTATIVE:
                record.state = PreferenceState.ESTABLISHED
            elif record.state == PreferenceState.ESTABLISHED:
                record.state = PreferenceState.STABLE
        return record

    @staticmethod
    def decay(record: PreferenceRecord, decay_factor: float = 0.05) -> PreferenceRecord:
        if record.stability in (
            PreferenceStability.SESSION,
            PreferenceStability.SHORT_TERM,
        ):
            record.confidence = max(0.0, record.confidence - decay_factor)
            if record.confidence < 0.3:
                record.state = PreferenceState.DECAYING
        return record

    @staticmethod
    def contradict(
        record: PreferenceRecord,
        new_value: Any,
        new_confidence: float,
    ) -> tuple[PreferenceRecord, PreferenceContradiction]:
        contradiction = PreferenceContradiction(
            contradiction_id=f"contra_{record.preference_id}",
            preference_id=record.preference_id,
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            old_value=record.value,
            new_value=new_value,
            old_state=record.state,
            new_state=PreferenceState.CONTRADICTED,
        )
        record.state = PreferenceState.CONTRADICTED
        record.contradiction_count += 1
        record.version += 1
        record.last_observed_at = datetime.utcnow()
        return record, contradiction

    @staticmethod
    def retire(record: PreferenceRecord) -> PreferenceRecord:
        record.state = PreferenceState.RETIRED
        record.confidence = 0.0
        return record

    @staticmethod
    def should_retire(record: PreferenceRecord) -> bool:
        if record.state == PreferenceState.RETIRED:
            return True
        if record.stability == PreferenceStability.SESSION:
            return False  # Session prefs expire via TTL, not retirement
        if record.contradiction_count >= 5 and record.confidence < 0.2:
            return True
        return False


__all__ = ["PreferenceLifecycle"]
