"""Runtime coordination for predictive continuity.

Runtime consumes already-authorized ContextEvidence. CORTEX owns ranking.
This service never retrieves memory independently, executes a suggestion, or
mutates user state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ai_karen_engine.core.context.contracts import CognitiveContext, EvidenceSource
from ai_karen_engine.core.cortex.continuity import (
    ContinuityPlan,
    ContinuityPlanner,
    ContinuityStateItem,
)


class ContinuityRuntime:
    """Adapt governed memory evidence into CORTEX continuity decisions."""

    def __init__(self, *, planner: ContinuityPlanner | None = None) -> None:
        self._planner = planner or ContinuityPlanner()

    def plan_from_context(
        self,
        *,
        query: str,
        cognitive_context: CognitiveContext | None,
        now: datetime | None = None,
        top_k: int = 5,
    ) -> ContinuityPlan:
        if not self._planner.should_plan(query):
            return ContinuityPlan(reason_codes=("continuity_not_requested",))
        if cognitive_context is None:
            return ContinuityPlan(reason_codes=("cognitive_context_missing",))

        items = [
            item
            for evidence in cognitive_context.evidence
            if evidence.source is EvidenceSource.MEMORY
            for item in [self._state_item(evidence)]
            if item is not None
        ]
        return self._planner.plan(
            query=query,
            items=items,
            now=now,
            top_k=top_k,
        )

    @staticmethod
    def _state_item(evidence: Any) -> ContinuityStateItem | None:
        envelope = dict(getattr(evidence, "metadata", {}) or {})
        memory_metadata = dict(envelope.get("memory_metadata") or {})
        custom = dict(memory_metadata.get("custom") or {})
        record_type = str(custom.get("record_type") or "").strip()

        source_type = {
            "memory_user_goal": "goal",
            "memory_open_loop": "open_loop",
            "memory_prospective_item": "prospective",
        }.get(record_type)
        if source_type is None:
            return None

        item_id = str(
            custom.get("goal_id")
            or custom.get("open_loop_id")
            or custom.get("prospective_id")
            or getattr(evidence, "evidence_id", "")
        ).strip()
        if not item_id:
            return None

        target_at = ContinuityRuntime._datetime(custom.get("target_at"))
        confidence = getattr(evidence, "confidence", None)
        if confidence is None:
            confidence = custom.get("confidence", 0.5)

        return ContinuityStateItem(
            item_id=item_id,
            source_type=source_type,
            description=str(getattr(evidence, "content", "") or "").strip(),
            confidence=max(0.0, min(1.0, float(confidence or 0.0))),
            lifecycle_state=str(custom.get("lifecycle_state") or ""),
            source_event_id=str(custom.get("event_id") or ""),
            target_at=target_at,
            domain=ContinuityRuntime._text_or_none(custom.get("domain")),
            metadata=custom,
        )

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _text_or_none(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None


__all__ = ["ContinuityRuntime"]
