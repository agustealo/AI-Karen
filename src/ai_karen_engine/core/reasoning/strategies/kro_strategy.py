"""KRO as a registered reasoning strategy.

Wraps the existing KROOrchestrator so it participates as a
reasoning strategy via dependency injection.
"""

from __future__ import annotations

from typing import Any, List

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningResult,
    ReasoningStatus,
    ReasoningStrategyEngine,
)
from ai_karen_engine.core.reasoning.kro_orchestrator import KROOrchestrator
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class KROReasoningStrategy(ReasoningStrategyEngine):
    """KRO as a reasoning strategy.

    It does not select providers, models, or execute tools directly.
    It uses the canonical reasoning contracts for input and output.
    """

    strategy_id = "kro"
    version = "v1"
    capabilities = ["synthesis", "classification", "evidence_gathering"]
    required_inputs = ["objective"]
    supports_model_calls = True
    supports_tools = False
    expected_cost = "medium"
    max_steps = 3
    output_contract = {
        "hypotheses": True,
        "evidence": True,
        "contradictions": True,
        "verification": True,
    }
    determinism = "generative"

    def __init__(self) -> None:
        self._orchestrator = KROOrchestrator()

    async def execute(
        self,
        request: Any,
        context: ExecutionContext,
        evidence: List[ReasoningEvidence],
        budget: ReasoningBudget,
    ) -> ReasoningResult:
        from ai_karen_engine.core.reasoning.contracts import ReasoningRequest

        canonical_request = request if isinstance(request, ReasoningRequest) else self._adapt(request)
        result = await self._orchestrator.run(canonical_request)
        return result

    def _adapt(self, request: Any) -> Any:
        from ai_karen_engine.core.reasoning.contracts import (
            ReasoningBudget,
            ReasoningEvidence,
            ReasoningRequest,
        )

        return ReasoningRequest(
            request_id=getattr(request, "request_id", ""),
            correlation_id=getattr(request, "correlation_id", ""),
            tenant_id=getattr(request, "tenant_id", "default"),
            user_id=getattr(request, "user_id", ""),
            conversation_id=getattr(request, "conversation_id", None),
            objective=str(getattr(request, "objective", "")),
            reasoning_modes=list(getattr(request, "reasoning_modes", []) or []),
            evidence=list(getattr(request, "evidence", []) or []),
            constraints=dict(getattr(request, "constraints", {}) or {}),
            policy_decision_id=getattr(request, "policy_decision_id", ""),
            budget=ReasoningBudget(),
            metadata=dict(getattr(request, "metadata", {}) or {}),
        )
