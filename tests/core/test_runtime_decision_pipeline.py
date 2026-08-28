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
from ai_karen_engine.core.runtime.policy import (
    PolicyDecision,
    PolicyReasonCode,
    RuntimePolicyEnforcer,
)


class FakeCortex:
    def __init__(self, decision: ExecutionDecision) -> None:
        self.decision = decision
        self.calls = 0

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        self.calls += 1
        return self.decision


class RecordingPolicy(RuntimePolicyEnforcer):
    def __init__(self) -> None:
        super().__init__()
        self.actions: list[str] = []

    async def evaluate(self, request):  # type: ignore[no-untyped-def]
        self.actions.append(request.action)
        return await super().evaluate(request)


class MemoryReadDenyingPolicy(RuntimePolicyEnforcer):
    def __init__(self) -> None:
        super().__init__()
        self.actions: list[str] = []

    async def evaluate(self, request):  # type: ignore[no-untyped-def]
        self.actions.append(request.action)
        if request.action == "context.resolve":
            return PolicyDecision(
                decision_id="policy-context-denied",
                policy_version="v2",
                allowed=True,
                reason_codes=[PolicyReasonCode.POLICY_CHECK_PASSED],
                allowed_capabilities=[],
                denied_capabilities=["memory.read"],
            )
        return await super().evaluate(request)


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
        assert result.policy_constraints["cortex_stage_2_context_id"].startswith(
            "context-"
        )

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


def test_memory_context_is_policy_gated_before_final_execution_policy() -> None:
    async def run() -> None:
        cognitive = ExecutionDecision(
            intent="remembered_assist",
            memory_recall_required=True,
            memory_scope="conversation",
            memory_top_k=7,
            memory_classes=["episodic"],
        )
        policy = RecordingPolicy()
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
            policy=policy,
        )

        result = await pipeline.decide(_request())

        assert policy.actions == ["context.resolve", "remembered_assist"]
        assert result.memory_recall_required is True
        assert "memory.read" in result.required_capabilities
        assert result.policy_constraints["context_authorized_sources"] == ["memory"]
        assert result.policy_constraints["context_unresolved_sources"] == ["memory"]
        requirements = result.policy_constraints["cortex_stage_1_context_requirements"]
        assert requirements["requirements"][0]["source"] == "memory"
        assert requirements["requirements"][0]["capability"] == "memory.read"
        assert requirements["requirements"][0]["scopes"] == ["conversation"]
        assert requirements["requirements"][0]["classes"] == ["episodic"]
        assert requirements["requirements"][0]["max_items"] == 7

    asyncio.run(run())


def test_denied_memory_context_degrades_to_no_recall_without_denial_of_chat() -> None:
    async def run() -> None:
        cognitive = ExecutionDecision(
            intent="general_assist",
            memory_recall_required=True,
            memory_scope="session",
            memory_top_k=5,
        )
        policy = MemoryReadDenyingPolicy()
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
            policy=policy,
        )

        result = await pipeline.decide(_request())

        assert policy.actions == ["context.resolve", "general_assist"]
        assert result.memory_recall_required is False
        assert "memory.read" not in result.required_capabilities
        assert "memory.read" in result.forbidden_capabilities
        assert "context_memory_denied_by_policy" in result.reason_codes
        assert result.policy_constraints["context_denied_sources"] == ["memory"]
        assert result.policy_decision_id is not None
        assert result.execution_mode != RuntimeExecutionMode.DEGRADED

    asyncio.run(run())
