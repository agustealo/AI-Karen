"""
Preference evidence management for AI-Karen personalization.

Evidence identity is tenant- and user-scoped. The store is an ephemeral runtime
accumulator only; durable evidence ownership belongs to the canonical memory /
persistence layer.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..contracts import PreferenceEvidence
from .catalog import PreferenceCatalog


EvidenceBucketKey = Tuple[str, str, str]


class PreferenceEvidenceStore:
    """Deduplicate and score preference evidence within one runtime instance.

    The store deliberately does not claim durability. Every bucket is keyed by
    ``(tenant_id, user_id, preference_key)`` so evidence from one subject can
    never affect another subject's confidence calculation.
    """

    def __init__(self) -> None:
        self._evidence: Dict[EvidenceBucketKey, List[PreferenceEvidence]] = {}

    @staticmethod
    def _identity(evidence: PreferenceEvidence) -> EvidenceBucketKey:
        tenant_id = str(evidence.metadata.get("tenant_id", "")).strip()
        user_id = str(evidence.metadata.get("user_id", "")).strip()
        if not tenant_id or not user_id:
            raise ValueError("preference evidence requires tenant_id and user_id metadata")
        return tenant_id, user_id, evidence.preference_key

    @staticmethod
    def _bucket_key(preference_key: str, user_id: str, tenant_id: str) -> EvidenceBucketKey:
        if not tenant_id or not user_id:
            raise ValueError("preference evidence lookup requires tenant_id and user_id")
        return tenant_id, user_id, preference_key

    def add(self, evidence: PreferenceEvidence) -> bool:
        bucket = self._identity(evidence)
        dedupe_key = self._dedupe_key(evidence)
        existing = self._evidence.setdefault(bucket, [])
        if any(self._dedupe_key(item) == dedupe_key for item in existing):
            return False
        existing.append(evidence)
        return True

    def get_for_preference(
        self,
        preference_key: str,
        *,
        user_id: str,
        tenant_id: str,
    ) -> List[PreferenceEvidence]:
        return list(self._evidence.get(self._bucket_key(preference_key, user_id, tenant_id), []))

    def compute_confidence(
        self,
        preference_key: str,
        base_confidence: float = 0.5,
        *,
        user_id: str,
        tenant_id: str,
    ) -> float:
        evidence_list = self.get_for_preference(
            preference_key,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        if not evidence_list:
            return base_confidence

        weighted_sum = 0.0
        weight_total = 0.0
        now = datetime.utcnow()

        for evidence in evidence_list:
            age_hours = (now - evidence.observed_at).total_seconds() / 3600.0
            recency = max(0.0, min(1.0, 1.0 - (age_hours / (24.0 * 30))))
            weight = PreferenceCatalog.get_evidence_weight(evidence.source_type) * (
                0.5 + 0.5 * recency
            )
            if evidence.polarity == "negative":
                weight *= 0.7
            weighted_sum += weight * evidence.confidence
            weight_total += weight

        if weight_total == 0:
            return base_confidence
        return max(0.0, min(1.0, weighted_sum / weight_total))

    def _dedupe_key(self, evidence: PreferenceEvidence) -> str:
        tenant_id, user_id, preference_key = self._identity(evidence)
        raw = "|".join(
            [
                tenant_id,
                user_id,
                preference_key,
                str(evidence.observed_value),
                evidence.source_type.value,
                evidence.source_ref or "",
                evidence.polarity,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def count(self, preference_key: str, *, user_id: str, tenant_id: str) -> int:
        return len(
            self._evidence.get(
                self._bucket_key(preference_key, user_id, tenant_id),
                [],
            )
        )


__all__ = ["PreferenceEvidenceStore"]
