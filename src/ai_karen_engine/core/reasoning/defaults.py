"""Default reasoning strategy factory.

Provides the canonical Core-safe strategy wiring for ReasoningExecutor.
Provider/model-specific strategies are injected by Runtime and are never
bootstrapped here.
"""

from __future__ import annotations

from typing import List, Optional

from ai_karen_engine.core.reasoning.executor import ReasoningExecutor
from ai_karen_engine.core.reasoning.strategies.causal_strategy import CausalReasoner
from ai_karen_engine.core.reasoning.strategies.metacognition_strategy import MetacognitionStrategy
from ai_karen_engine.core.reasoning.strategies.refiner_strategy import Refiner
from ai_karen_engine.core.reasoning.strategies.verifier_strategy import Verifier
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine


def get_default_strategies(
    *,
    optional_strategies: Optional[List[ReasoningStrategyEngine]] = None,
) -> List[ReasoningStrategyEngine]:
    """Return Core-safe defaults plus explicitly runtime-injected capabilities.

    Soft Reasoning is intentionally absent unless Runtime injects a configured
    ``SoftReasoner`` backed by a model runtime that supports first-token
    embedding control.
    """
    strategies: List[ReasoningStrategyEngine] = [
        CausalReasoner(),
        Verifier(),
        Refiner(),
        MetacognitionStrategy(),
    ]
    if optional_strategies:
        strategies = list(optional_strategies) + strategies
    return strategies


def get_default_executor(
    strategies: Optional[List[ReasoningStrategyEngine]] = None,
    *,
    optional_strategies: Optional[List[ReasoningStrategyEngine]] = None,
) -> ReasoningExecutor:
    """Return a ReasoningExecutor with explicit or canonical strategy wiring."""
    resolved = (
        list(strategies)
        if strategies is not None
        else get_default_strategies(optional_strategies=optional_strategies)
    )
    return ReasoningExecutor(strategies=resolved)
