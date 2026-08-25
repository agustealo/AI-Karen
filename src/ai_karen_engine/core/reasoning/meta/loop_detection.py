from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.reasoning.meta.contracts import (
    LoopAssessment,
    LoopDetectionStrategy,
    MetaReasonCode,
    StrategyAttempt,
    StrategyFingerprint,
)

logger = logging.getLogger(__name__)


class LoopDetector:
    """Detects reasoning loops from strategy attempts."""

    def detect(self, attempts: list[StrategyAttempt]) -> LoopAssessment:
        """Detect if reasoning is in a loop."""
        if len(attempts) < 3:
            return LoopAssessment(is_looping=False, loop_count=len(attempts))

        fingerprints = []
        for a in attempts:
            evidence_hash = hashlib.sha256("|".join(a.evidence_hashes or []).encode()).hexdigest()[:16]
            fingerprints.append(StrategyFingerprint(
                strategy_type=a.strategy_type,
                evidence_hash=evidence_hash,
                outcome_class=a.outcome,
            ))

        loop_count = 0
        for i in range(len(fingerprints) - 2):
            window = fingerprints[i:i+3]
            if all(f.strategy_type == window[0].strategy_type and f.evidence_hash == window[0].evidence_hash for f in window):
                loop_count += 1

        if loop_count >= 1:
            return LoopAssessment(
                is_looping=True,
                loop_count=loop_count,
                fingerprint=fingerprints[-1],
            )
        return LoopAssessment(is_looping=False, loop_count=loop_count)

    def recommend_action(self, assessment: LoopAssessment) -> str:
        if not assessment.is_looping:
            return "continue"
        return "change_strategy"
