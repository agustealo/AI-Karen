"""
Preference evidence management for AI-Karen personalization.

Tracks, deduplicates, and weights preference evidence.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..contracts import (
    PreferenceEvidence,
    PreferenceEvidenceSourceType,
    PreferenceRecord,
)
from .catalog import PreferenceCatalog


class PreferenceEvidenceStore:
    """Stores and manages preference evidence."""

    def __init__(self):
        self._evidence: Dict[str, List[PreferenceEvidence]] = {}

    def add(self, evidence: PreferenceEvidence) -> bool:
        key = self._dedupe_key(evidence)
        existing = self._evidence.get(evidence.preference_key, [])
        for e in existing:
            if self._dedupe_key(e) == key:
                return False
        existing.append(evidence)
        self._evidence[evidence.preference_key] = existing
        return True

    def get_for_preference(self, preference_key: str) -> List[PreferenceEvidence]:
        return list(self._evidence.get(preference_key, []))

    def compute_confidence(self, preference_key: str, base_confidence: float = 0.5) -> float:
        evidence_list = self.get_for_preference(preference_key)
        if not evidence_list:
            return base_confidence

        weighted_sum = 0.0
        weight_total = 0.0
        now = datetime.utcnow()

        for e in evidence_list:
            age_hours = (now - e.observed_at).total_seconds() / 3600.0
            recency = max(0.0, min(1.0, 1.0 - (age_hours / (24.0 * 30))))
            weight = PreferenceCatalog.get_evidence_weight(e.source_type) * (0.5 + 0.5 * recency)
            if e.polarity == "negative":
                weight *= 0.7
            weighted_sum += weight * e.confidence
            weight_total += weight

        if weight_total == 0:
            return base_confidence
        return max(0.0, min(1.0, weighted_sum / weight_total))

    def _dedupe_key(self, evidence: PreferenceEvidence) -> str:
        raw = "|".join([
            evidence.preference_key,
            str(evidence.observed_value),
            evidence.source_type.value,
            evidence.source_ref or "",
            evidence.polarity,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def count(self, preference_key: str) -> int:
        return len(self._evidence.get(preference_key, []))


__all__ = ["PreferenceEvidenceStore"]
