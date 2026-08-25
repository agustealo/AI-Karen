from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ai_karen_engine.core.adaptive.salience.contracts import (
    SalienceDimension,
    SalienceReasonCode,
    SalienceSignal,
    SalienceAssessment,
)


@dataclass(slots=True)
class DecayResult:
    """Result of applying salience decay."""
    decayed_value: float = 0.0
    decayed: bool = False
    decayed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class SalienceDecayEngine:
    """Applies time-based and event-based decay to salience signals."""

    def decay_signal(self, signal: SalienceSignal) -> DecayResult:
        """Decay a single salience signal."""
        if signal.persistence_class == "persistent":
            return DecayResult(decayed_value=signal.value, decayed=False)

        if signal.last_activated_at:
            try:
                last = datetime.fromisoformat(signal.last_activated_at)
                elapsed_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
                decay_factor = math.exp(-signal.decay_rate * elapsed_hours)
                new_value = signal.value * decay_factor
            except (ValueError, TypeError):
                new_value = signal.value
        else:
            new_value = signal.value

        decayed = new_value < signal.value
        return DecayResult(decayed_value=max(0.0, min(1.0, new_value)), decayed=decayed)

    def decay_assessment(self, assessment: SalienceAssessment) -> SalienceAssessment:
        """Decay an entire assessment in place."""
        result = SalienceAssessment(
            novelty=self._decay_value(assessment.novelty, 0.1),
            urgency=self._decay_value(assessment.urgency, 0.2),
            goal_relevance=self._decay_value(assessment.goal_relevance, 0.05),
            relationship_importance=self._decay_value(assessment.relationship_importance, 0.03),
            risk=self._decay_value(assessment.risk, 0.15),
            surprise=self._decay_value(assessment.surprise, 0.2),
            reward_significance=self._decay_value(assessment.reward_significance, 0.1),
            failure_significance=self._decay_value(assessment.failure_significance, 0.05),
            success_significance=self._decay_value(assessment.success_significance, 0.1),
            repetition=self._decay_value(assessment.repetition, 0.1),
            unresolved_state=assessment.unresolved_state,
            contradiction=self._decay_value(assessment.contradiction, 0.05),
            interruption_cost=self._decay_value(assessment.interruption_cost, 0.2),
            user_emphasis=assessment.user_emphasis,
            confidence=assessment.confidence,
            reason_codes=list(assessment.reason_codes),
            source_refs=list(assessment.source_refs),
            metadata=dict(assessment.metadata),
        )
        return result

    def _decay_value(self, value: float, rate: float) -> float:
        return max(0.0, min(1.0, value * (1.0 - rate)))
