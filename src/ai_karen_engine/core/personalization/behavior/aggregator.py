"""Behavior aggregation for user personalization.

This layer consumes explicit user-behavior observations. Runtime/provider
success, fallbacks, latency, and model routing are ML/OPE evidence and must not
be re-labeled as user behavior.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ..contracts import (
    BehaviorCandidate,
    BehaviorPattern,
    PreferenceStability,
)
from .contracts import BehaviorObservation


class BehaviorAggregator:
    """Convert observed user behavior into recurrence candidates."""

    def observe(self, observation: BehaviorObservation) -> BehaviorCandidate:
        confidence = float(observation.metadata.get("confidence", 0.5) or 0.5)
        return BehaviorCandidate(
            candidate_id=f"cand_{uuid.uuid4().hex[:16]}",
            user_id=observation.user_id,
            tenant_id=observation.tenant_id,
            pattern_type=observation.action,
            context_signature=observation.context_signature,
            observation=observation.outcome,
            confidence=max(0.0, min(1.0, confidence)),
            metadata={
                **dict(observation.metadata),
                "observation_id": observation.observation_id,
                "observed_at": observation.observed_at.isoformat(),
            },
        )

    def promote_candidates(
        self,
        candidates: list[BehaviorCandidate],
    ) -> list[BehaviorPattern]:
        """Pure helper used for offline/test aggregation; no hidden persistence."""

        promoted: list[BehaviorPattern] = []
        buckets: dict[str, list[BehaviorCandidate]] = {}
        for candidate in candidates:
            signature = (
                f"{candidate.user_id}:{candidate.tenant_id}:"
                f"{candidate.pattern_type}:{candidate.context_signature}"
            )
            buckets.setdefault(signature, []).append(candidate)

        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            first = bucket[0]
            observed_times = [
                self._observed_at(candidate) for candidate in bucket
            ]
            promoted.append(
                BehaviorPattern(
                    pattern_id=first.candidate_id.replace("cand_", "pat_"),
                    user_id=first.user_id,
                    tenant_id=first.tenant_id,
                    pattern_type=first.pattern_type,
                    context_signature=first.context_signature,
                    observation_count=len(bucket),
                    confidence=min(1.0, 0.3 + 0.1 * len(bucket)),
                    first_seen=min(observed_times),
                    last_seen=max(observed_times),
                    recurrence="recurring" if len(bucket) >= 3 else "repeated",
                    stability=PreferenceStability.SHORT_TERM,
                )
            )
        return promoted

    @staticmethod
    def _observed_at(candidate: BehaviorCandidate) -> datetime:
        raw = candidate.metadata.get("observed_at")
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                pass
        return datetime.utcnow()


__all__ = ["BehaviorAggregator"]
