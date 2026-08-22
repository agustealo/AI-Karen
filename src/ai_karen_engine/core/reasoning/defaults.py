"""Default reasoning strategy factory.

Provides sensible default strategy wiring for ReasoningExecutor.
No registry is used; strategies are injected directly.
"""

from __future__ import annotations

from typing import List, Optional

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningEvidence,
    ReasoningStrategyEngine,
)
from ai_karen_engine.core.reasoning.executor import ReasoningExecutor
from ai_karen_engine.core.reasoning.strategies.causal_strategy import CausalReasoner
from ai_karen_engine.core.reasoning.strategies.metacognition_strategy import MetacognitionStrategy
from ai_karen_engine.core.reasoning.strategies.refiner_strategy import Refiner
from ai_karen_engine.core.reasoning.strategies.soft_strategy import SoftReasoner
from ai_karen_engine.core.reasoning.strategies.verifier_strategy import Verifier
from ai_karen_engine.core.reasoning.strategies.kro_strategy import KROReasoningStrategy


def get_default_strategies() -> List[ReasoningStrategyEngine]:
    """Return the default ordered list of reasoning strategies."""
    return [
        SoftReasoner(),
        CausalReasoner(),
        Verifier(),
        Refiner(),
        MetacognitionStrategy(),
        KROReasoningStrategy(),
    ]


def get_default_executor(
    strategies: Optional[List[ReasoningStrategyEngine]] = None,
) -> ReasoningExecutor:
    """Return a ReasoningExecutor wired with default strategies."""
    return ReasoningExecutor(strategies=strategies or get_default_strategies())
