"""
Behavior aggregation for AI-Karen personalization.

Learns behavior patterns from outcomes and memory artifacts asynchronously.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..contracts import (
    BehaviorCandidate,
    BehaviorPattern,
    PreferenceStability,
)
from .contracts import BehaviorObservation, BehaviorPatternStore


class BehaviorAggregator:
    """Aggregates behavior patterns from observations."""

    def __init__(self, store: Optional[BehaviorPatternStore] = None):
        self.store = store or BehaviorPatternStore()

    def ingest_outcome(self, outcome: Any) -> List[BehaviorCandidate]:
        candidates: List[BehaviorCandidate] = []
        record = getattr(outcome, "execution_outcome", None)
        if not record:
            return candidates

        ctx = getattr(outcome, "metadata", {}) or {}
        user_id = getattr(outcome, "user_id", "unknown") or "unknown"
        tenant_id = getattr(outcome, "tenant_id", "default") or "default"

        if getattr(record, "tool_success", None) is True:
            candidates.append(self._make_candidate(
                user_id, tenant_id, "tool_success", ctx, "tool succeeded", 0.6
            ))
        if getattr(record, "fallback_count", 0) > 0:
            candidates.append(self._make_candidate(
                user_id, tenant_id, "fallback_used", ctx, "fallback triggered", 0.4
            ))
        if getattr(record, "response_completed", None) is False:
            candidates.append(self._make_candidate(
                user_id, tenant_id, "response_incomplete", ctx, "response incomplete", 0.5
            ))
        return candidates

    def ingest_memory_artifact(self, artifact: Any) -> List[BehaviorCandidate]:
        candidates: List[BehaviorCandidate] = []
        payload = getattr(artifact, "content", {}) or {}
        if not isinstance(payload, dict):
            return candidates
        user_id = getattr(artifact, "user_id", "unknown") or "unknown"
        tenant_id = getattr(artifact, "tenant_id", "default") or "default"
        text = str(payload.get("text", ""))
        if "audit" in text.lower():
            candidates.append(self._make_candidate(
                user_id, tenant_id, "audit_workflow", payload, "audit workflow observed", 0.5
            ))
        return candidates

    def promote_candidates(self, candidates: List[BehaviorCandidate]) -> List[BehaviorPattern]:
        promoted: List[BehaviorPattern] = []
        buckets: Dict[str, List[BehaviorCandidate]] = {}
        for c in candidates:
            sig = f"{c.user_id}:{c.tenant_id}:{c.pattern_type}:{c.context_signature}"
            buckets.setdefault(sig, []).append(c)

        for sig, bucket in buckets.items():
            if len(bucket) < 2:
                continue
            first = bucket[0]
            pattern = BehaviorPattern(
                pattern_id=first.candidate_id.replace("cand_", "pat_"),
                user_id=first.user_id,
                tenant_id=first.tenant_id,
                pattern_type=first.pattern_type,
                context_signature=first.context_signature,
                observation_count=len(bucket),
                confidence=min(1.0, 0.3 + 0.1 * len(bucket)),
                first_seen=bucket[0].metadata.get("observed_at", datetime.utcnow()),
                last_seen=bucket[-1].metadata.get("observed_at", datetime.utcnow()),
                recurrence="recurring" if len(bucket) >= 3 else "observed",
                stability=PreferenceStability.SHORT_TERM,
            )
            self.store.upsert(pattern)
            promoted.append(pattern)
        return promoted

    def _make_candidate(
        self,
        user_id: str,
        tenant_id: str,
        pattern_type: str,
        context: Dict[str, Any],
        observation: str,
        confidence: float,
    ) -> BehaviorCandidate:
        ctx_sig = self._signature(context)
        return BehaviorCandidate(
            candidate_id=f"cand_{uuid.uuid4().hex[:16]}",
            user_id=user_id,
            tenant_id=tenant_id,
            pattern_type=pattern_type,
            context_signature=ctx_sig,
            observation=observation,
            confidence=confidence,
            metadata={"observed_at": datetime.utcnow().isoformat()},
        )

    @staticmethod
    def _signature(context: Dict[str, Any]) -> str:
        keys = sorted(context.keys())
        return "|".join(f"{k}={context.get(k)}" for k in keys[:5])


__all__ = ["BehaviorAggregator"]
