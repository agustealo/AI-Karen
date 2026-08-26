"""Reasoning strategy base and registry.

Each strategy declares its capabilities, determinism, cost model, and output
contract. CORTEX/RuntimePolicy request modes; Runtime resolves registered
strategies. Strategies must never choose each other ad hoc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningResult,
)
from ai_karen_engine.core.runtime.contracts import ExecutionContext


@dataclass(frozen=True, slots=True)
class ReasoningStrategyModel:
    """Serializable strategy descriptor exposed by the canonical registry."""

    strategy_id: str
    version: str
    capabilities: List[str] = field(default_factory=list)
    required_inputs: List[str] = field(default_factory=list)
    supports_model_calls: bool = False
    supports_tools: bool = False
    expected_cost: str = "low"
    max_steps: int = 5
    output_contract: Dict[str, Any] = field(default_factory=dict)
    determinism: str = "deterministic"


class ReasoningStrategyEngine(ABC):
    """Abstract base for one bounded reasoning algorithm.

    A strategy does not orchestrate other strategies and does not select
    providers, models, tools, plugins, memory stores, or execution topology.
    """

    strategy_id: str = "abstract"
    version: str = "v1"
    capabilities: List[str] = []
    required_inputs: List[str] = []
    supports_model_calls: bool = False
    supports_tools: bool = False
    expected_cost: str = "low"
    max_steps: int = 5
    output_contract: Dict[str, Any] = {}
    determinism: str = "deterministic"

    @abstractmethod
    async def execute(
        self,
        request: Any,
        context: ExecutionContext,
        evidence: List[ReasoningEvidence],
        budget: ReasoningBudget,
    ) -> ReasoningResult:
        """Execute this strategy and return a typed ReasoningResult."""
        ...

    def can_handle(self, modes: List[str]) -> bool:
        return any(mode in self.capabilities for mode in modes)

    def estimate_cost(self, modes: List[str]) -> str:
        return self.expected_cost


class ReasoningStrategyRegistry:
    """Canonical registry for reasoning strategies."""

    def __init__(self) -> None:
        self._strategies: Dict[str, ReasoningStrategyEngine] = {}

    def register(self, strategy: ReasoningStrategyEngine) -> None:
        if not strategy.strategy_id or strategy.strategy_id == "abstract":
            raise ValueError("reasoning strategy requires a concrete strategy_id")
        self._strategies[strategy.strategy_id] = strategy

    def get(self, strategy_id: str) -> Optional[ReasoningStrategyEngine]:
        return self._strategies.get(strategy_id)

    def list_strategies(self) -> List[ReasoningStrategyEngine]:
        return list(self._strategies.values())

    def resolve_for_modes(self, modes: List[str]) -> List[ReasoningStrategyEngine]:
        resolved: List[ReasoningStrategyEngine] = []
        seen: set[str] = set()
        for mode in modes:
            for strategy in self._strategies.values():
                if strategy.can_handle([mode]) and strategy.strategy_id not in seen:
                    resolved.append(strategy)
                    seen.add(strategy.strategy_id)
        return resolved

    def to_model(self, strategy: ReasoningStrategyEngine) -> ReasoningStrategyModel:
        return ReasoningStrategyModel(
            strategy_id=strategy.strategy_id,
            version=strategy.version,
            capabilities=list(strategy.capabilities),
            required_inputs=list(strategy.required_inputs),
            supports_model_calls=strategy.supports_model_calls,
            supports_tools=strategy.supports_tools,
            expected_cost=strategy.expected_cost,
            max_steps=strategy.max_steps,
            output_contract=dict(strategy.output_contract),
            determinism=strategy.determinism,
        )


_registry: Optional[ReasoningStrategyRegistry] = None


def get_reasoning_strategy_registry() -> ReasoningStrategyRegistry:
    global _registry
    if _registry is None:
        _registry = ReasoningStrategyRegistry()
    return _registry
