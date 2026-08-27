from __future__ import annotations

import asyncio

from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
    RuntimeExecutionMode,
)
from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer


class FakeCortex:
    def __init__(self, decision: ExecutionDecision) -> None:
        self.decision = decision
        self.calls = 0

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        self.calls += 1
        return self.decision


def _request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "reason about this"}],
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id="tenant-1",
            session_id="session-1",
            permissions=[],
        ),
    )


def test_pipeline_authorizes_reasoning_after_cortex() -> None:
    async def run() -> None:
        cognitive = ExecutionDecision(
            topology=ExecutionTopology.REASONING,
            reasoning_modes=["verification"],
            max_model_calls=10,
        )
        cortex = FakeCortex(cognitive)
        pipeline = RuntimeDecisionPipeline(
            cortex=cortex,  # type: ignore[arg-type]
            policy=RuntimePolicyEnforcer(),
        )
        result = await pipeline.decide(_request())
        assert cortex.calls == 1
        assert result.reasoning_modes == ["verification"]
        assert result.policy_decision_id is not None
        assert result.policy_version == "v2"

    asyncio.run(run())


def test_pipeline_drops_policy_denied_soft_exploration_without_inventing_mode() -> None:
    async def run() -> None:
        cognitive = ExecutionDecision(
            topology=ExecutionTopology.REASONING,
            reasoning_modes=["soft_exploration"],
            max_model_calls=10,
        )
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
            policy=RuntimePolicyEnforcer(),
        )
        result = await pipeline.decide(_request())
        assert result.reasoning_modes == []
        assert result.topology == ExecutionTopology.DIRECT
        assert result.execution_mode == RuntimeExecutionMode.DIRECT
        assert result.policy_constraints["denied_reasoning_modes"] == [
            "soft_exploration"
        ]

    asyncio.run(run())


def test_pipeline_memory_write_is_false_until_policy_grants_capability() -> None:
    async def run() -> None:
        cognitive = ExecutionDecision(
            required_capabilities=[],
            memory_write_allowed=False,
            policy_constraints={"memory_write_requested": True},
        )
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
            policy=RuntimePolicyEnforcer(),
        )
        result = await pipeline.decide(_request())
        assert result.memory_write_allowed is False

    asyncio.run(run())


def test_pipeline_memory_write_becomes_true_only_when_requested_capability_is_allowed() -> None:
    async def run() -> None:
        cognitive = ExecutionDecision(
            required_capabilities=["memory.write"],
            memory_write_allowed=False,
            policy_constraints={"memory_write_requested": True},
        )
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
            policy=RuntimePolicyEnforcer(),
        )
        result = await pipeline.decide(_request())
        assert result.memory_write_allowed is True
        assert "memory.write" in result.required_capabilities

    asyncio.run(run())
