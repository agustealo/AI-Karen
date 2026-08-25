"""
Memory Policies for AI-Karen

This module defines policies for:
- Salience scoring
- Forgetting (decay, suppression, consolidation)
- Consolidation triggers
- Retrieval budget

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai_karen_engine.core.memory.contracts import SalienceScore

# ===================================
# SALIENCE SCORING POLICY
# ===================================

@dataclass
class SaliencePolicy:
    """
    Policy for computing salience scores.
    """
    novelty_weight: float = 1.0
    surprise_weight: float = 1.0
    user_emphasis_weight: float = 2.0
    goal_relevance_weight: float = 1.5
    consequence_weight: float = 1.5
    repetition_weight: float = 0.5
    relationship_relevance_weight: float = 1.0
    decision_importance_weight: float = 1.5
    error_significance_weight: float = 1.2
    success_significance_weight: float = 1.0

    def compute(self, score: SalienceScore) -> float:
        """Compute weighted salience score."""
        return (
            score.novelty * self.novelty_weight +
            score.surprise * self.surprise_weight +
            score.user_emphasis * self.user_emphasis_weight +
            score.goal_relevance * self.goal_relevance_weight +
            score.consequence * self.consequence_weight +
            score.repetition * self.repetition_weight +
            score.relationship_relevance * self.relationship_relevance_weight +
            score.decision_importance * self.decision_importance_weight +
            score.error_significance * self.error_significance_weight +
            score.success_significance * self.success_significance_weight
        )


# ===================================
# FORGETTING POLICY
# ===================================

@dataclass
class ForgettingPolicy:
    """
    Policy for controlled forgetting.

    Three mechanisms:
    - DECAY: low-value unused memories become less retrievable
    - SUPPRESSION: irrelevant memories lose activation in current context
    - CONSOLIDATION: many similar episodes become stronger generalized memory
    """
    decay_half_life_days: float = 30.0
    suppression_threshold: float = 0.1
    consolidation_min_episodes: int = 5
    consolidation_min_confidence: float = 0.8
    staleness_penalty_per_day: float = 0.01
    min_retention_score: float = 0.1

    def compute_decay_factor(self, days_since_access: float) -> float:
        """Compute decay factor based on time since last access."""
        import math
        return math.exp(-days_since_access * math.log(2) / self.decay_half_life_days)

    def should_consolidate(self, episode_count: int, confidence: float) -> bool:
        """Determine if episodes should be consolidated into semantic memory."""
        return episode_count >= self.consolidation_min_episodes and confidence >= self.consolidation_min_confidence

    def compute_staleness_penalty(self, last_confirmed: datetime | None) -> float:
        """Compute staleness penalty based on time since last confirmation."""
        if last_confirmed is None:
            return 0.5  # Default penalty for unconfirmed memories
        days = (datetime.utcnow() - last_confirmed).total_seconds() / 86400.0
        return min(1.0, days * self.staleness_penalty_per_day)


# ===================================
# CONSOLIDATION POLICY
# ===================================

@dataclass
class ConsolidationPolicy:
    """
    Policy for memory consolidation.
    """
    min_episodes_for_consolidation: int = 5
    min_confidence_for_consolidation: float = 0.8
    max_consolidation_candidates: int = 100
    replay_window_days: int = 7
    reflection_interval_hours: int = 24

    def is_consolidation_candidate(self, episode_count: int, confidence: float) -> bool:
        """Check if a memory is a candidate for consolidation."""
        return episode_count >= self.min_episodes_for_consolidation and confidence >= self.min_confidence_for_consolidation


# ===================================
# RETRIEVAL POLICY
# ===================================

@dataclass
class RetrievalPolicy:
    """
    Policy for memory retrieval.
    """
    max_results: int = 10
    min_confidence_threshold: float = 0.3
    temporal_decay_enabled: bool = True
    associative_activation_enabled: bool = True
    contradiction_penalty: float = 0.2
    staleness_penalty_per_day: float = 0.01
