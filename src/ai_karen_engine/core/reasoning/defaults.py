"""Default reasoning strategy factory.

Provides the canonical default strategy wiring for ReasoningExecutor.
Strategies are injected directly. This module must not bootstrap provider,
tool, UI, persistence, or orchestration authority.
"""

from __future__ import annotations

from typing import List, Optional

from ai_karen_engine.core.reasoning.contracts import ReasoningStrategyEngine
from ai_karen_engine.core.reasoning.executor import ReasoningExecutor
from ai_karen_engine.core.reasoning.strategies.causal_strategy import CausalReasoner
from ai_karen_engine.core.reasoning.strategies.metacognition_strategy import MetacognitionStrategy
from ai_karen_engine.core.reasoning.strategies.refiner_strategy import Refiner
from ai_karen_engine.core.reasoning.strategies.soft_strategy import SoftReasoner
from ai_karen_engine.core.reasoning.strategies.verifier_strategy import Verifier


def get_default_strategies() -> List[ReasoningStrategyEngine]:
    """Return the ordered, Core-safe default reasoning strategies."""
    return [
        SoftReasoner(),
        CausalReasoner(),
        Verifier(),
        Refiner(),
        MetacognitionStrategy(),
    ]


def get_default_executor(
    strategies: Optional[List[ReasoningStrategyEngine]] = None,
) -> ReasoningExecutor:
    """Return a ReasoningExecutor wired with explicit or canonical strategies."""
    return ReasoningExecutor(strategies=strategies or get_default_strategies())
