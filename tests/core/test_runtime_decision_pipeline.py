from __future__ import annotations

import asyncio

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.config.runtime import FeatureFlags, RuntimeSettings
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


class NoEvidenceResolver:
    """Keep policy unit tests deterministic and independent of live storage."""

    async def resolve(self, request, cognitive_context):
        return cognitive_context


def _request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "reason about this"}],
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id="tenant-1",
            session_id="session-1",
            permissions=[],
            authenticated_user=UserData(
                user_id="user-1",
                tenant_id="tenant-1",
                roles=["user"],
                permissions=[],
                is_active=True,
                is_verified=True,
            ),
        ),
    )


def test_untrusted_diagnostics_analyzes_without_model_execution_authority() -> None:
    async def run() -> None:
        request = _request()
        request.context.authenticated_user = None
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(
                ExecutionDecision(
                    topology=ExecutionTopology.DIRECT,
                    max_model_calls=1,
                ),
            ),
            policy=RuntimePolicyEnforcer(),
            evidence_resolver=NoEvidenceResolver(),
        )
        decision = await pipeline.decide(request)
        assert decision.policy_decision_id
        assert "_runtime_policy_issuance" not in request.context.__dict__

        from ai_karen_engine.core.runtime.contracts import (
            AuthorizedExecutionPlan, ExecutionBudget, ExecutionBudgetMeter,
        )
        budget = ExecutionBudget(max_model_calls=1)
        plan = AuthorizedExecutionPlan(
            execution_id="diagnostics-only",
            policy_decision_id=decision.policy_decision_id,
            authorized_user_id=request.context.user_id,
            authorized_tenant_id=request.context.tenant_id,
            authorized_session_id=request.context.session_id,
            budget=budget,
        )
        try:
            request.context.bind_runtime_model_authority(
                plan, ExecutionBudgetMeter(budget),
            )
        except PermissionError as exc:
            assert "authenticated_principal_required" in str(exc)
        else:
            raise AssertionError("diagnostics incorrectly granted execution")

    asyncio.run(run())


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
            evidence_resolver=NoEvidenceResolver(),
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
            evidence_resolver=NoEvidenceResolver(),
        )
        result = await pipeline.decide(_request())
        assert result.reasoning_modes == []
        assert result.topology == ExecutionTopology.DIRECT
        assert result.execution_mode == RuntimeExecutionMode.DIRECT
        assert result.policy_constraints["denied_reasoning_modes"] == [
            "soft_exploration"
        ]

    asyncio.run(run())


def test_pipeline_memory_write_requires_explicit_capability_and_policy() -> None:
    # Test the final policy gate directly: CORTEX's separate formation owner
    # may legitimately add a memory.write request for user interactions.
    cognitive = ExecutionDecision(
        required_capabilities=[],
        memory_write_allowed=False,
        policy_constraints={"memory_write_requested": True},
    )
    policy = PolicyDecision(
        decision_id="policy-memory",
        policy_version="v2",
        allowed=True,
        allowed_capabilities=["memory.write"],
    )
    pipeline = RuntimeDecisionPipeline(
        cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
        policy=RuntimePolicyEnforcer(),
        evidence_resolver=NoEvidenceResolver(),
    )

    result = pipeline._apply_execution_policy(cognitive, policy)

    assert result.memory_write_allowed is False
    assert result.policy_decision_id == "policy-memory"


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
            evidence_resolver=NoEvidenceResolver(),
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
            evidence_resolver=NoEvidenceResolver(),
        )

        result = await pipeline.decide(_request())

        assert policy.actions == ["context.resolve", "remembered_assist"]
        assert result.memory_recall_required is True
        assert "memory.read" in result.required_capabilities
        assert "memory" in result.policy_constraints["context_authorized_sources"]
        assert "memory" in result.policy_constraints["context_unresolved_sources"]
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
            evidence_resolver=NoEvidenceResolver(),
        )

        result = await pipeline.decide(_request())

        assert policy.actions == ["context.resolve", "general_assist"]
        assert result.memory_recall_required is False
        assert "memory.read" not in result.required_capabilities
        assert "memory.read" in result.forbidden_capabilities
        assert "context_memory_denied_by_policy" in result.reason_codes
        assert "memory" in result.policy_constraints["context_denied_sources"]
        assert result.policy_decision_id is not None
        assert result.execution_mode != RuntimeExecutionMode.DEGRADED

    asyncio.run(run())


def test_optional_verification_policy_probe_is_default_off(monkeypatch) -> None:
    from ai_karen_engine.core.runtime import decision_pipeline

    async def run() -> None:
        monkeypatch.setattr(
            decision_pipeline,
            "get_runtime_settings",
            lambda: RuntimeSettings(),
        )
        cognitive = ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            intent_confidence=0.95,
            policy_constraints={
                "response_strategy_policy_probe": {
                    "schema_version": "forged_by_cortex",
                    "policy_permitted_actions": ["verify_then_respond"],
                }
            },
        )
        policy = RecordingPolicy()
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
            policy=policy,
            evidence_resolver=NoEvidenceResolver(),
        )
        decision = await pipeline.decide(_request())
        assert decision.topology == ExecutionTopology.DIRECT
        assert decision.reasoning_modes == []
        assert "response_strategy_policy_probe" not in decision.policy_constraints
        assert policy.actions.count("general_assist") == 1

    asyncio.run(run())


def test_read_only_probe_reuses_scoped_runtime_policy_without_rerouting(
    monkeypatch,
) -> None:
    from ai_karen_engine.core.runtime import decision_pipeline

    async def run() -> None:
        monkeypatch.setattr(
            decision_pipeline,
            "get_runtime_settings",
            lambda: RuntimeSettings(
                features=FeatureFlags(
                    enable_verification_strategy_policy_probe=True,
                )
            ),
        )
        policy = RecordingPolicy()
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(
                ExecutionDecision(
                    topology=ExecutionTopology.DIRECT,
                    intent_confidence=0.95,
                )
            ),  # type: ignore[arg-type]
            policy=policy,
            evidence_resolver=NoEvidenceResolver(),
        )
        decision = await pipeline.decide(_request())
        proof = decision.policy_constraints["response_strategy_policy_probe"]
        assert proof["schema_version"] == "response_strategy_policy_probe_v1"
        assert proof["source_decision_id"] == decision.policy_decision_id
        assert proof["source_policy_version"] == decision.policy_version
        assert proof["policy_permitted_actions"] == [
            "respond_direct", "verify_then_respond",
        ]
        assert proof["execution_eligibility_established"] is False
        assert proof["randomized_selection"] is False
        assert proof["ope_eligible"] is False
        assert policy.actions.count("general_assist") == 2
        assert decision.topology == ExecutionTopology.DIRECT
        assert decision.reasoning_modes == []

    asyncio.run(run())


def test_reasoning_required_never_receives_optional_direct_policy_probe(
    monkeypatch,
) -> None:
    from ai_karen_engine.core.runtime import decision_pipeline

    async def run() -> None:
        monkeypatch.setattr(
            decision_pipeline,
            "get_runtime_settings",
            lambda: RuntimeSettings(
                features=FeatureFlags(
                    enable_verification_strategy_policy_probe=True,
                )
            ),
        )
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(
                ExecutionDecision(
                    topology=ExecutionTopology.REASONING,
                    reasoning_modes=["verification"],
                    intent_confidence=0.91,
                )
            ),  # type: ignore[arg-type]
            policy=RuntimePolicyEnforcer(),
            evidence_resolver=NoEvidenceResolver(),
        )
        decision = await pipeline.decide(_request())
        assert decision.topology == ExecutionTopology.REASONING
        assert decision.reasoning_modes == ["verification"]
        assert "response_strategy_policy_probe" not in decision.policy_constraints

    asyncio.run(run())


def test_optional_probe_failure_never_blocks_authorized_direct_chat(
    monkeypatch,
) -> None:
    from ai_karen_engine.core.runtime import decision_pipeline

    class BrokenAlternativePolicy(RuntimePolicyEnforcer):
        async def evaluate(self, request):  # type: ignore[no-untyped-def]
            if request.requested_reasoning_modes == ["verification"]:
                raise RuntimeError("shadow evaluator unavailable")
            return await super().evaluate(request)

    async def run() -> None:
        monkeypatch.setattr(
            decision_pipeline,
            "get_runtime_settings",
            lambda: RuntimeSettings(
                features=FeatureFlags(
                    enable_verification_strategy_policy_probe=True,
                )
            ),
        )
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(
                ExecutionDecision(
                    topology=ExecutionTopology.DIRECT,
                    intent_confidence=0.96,
                )
            ),  # type: ignore[arg-type]
            policy=BrokenAlternativePolicy(),
            evidence_resolver=NoEvidenceResolver(),
        )
        result = await pipeline.decide(_request())
        assert result.topology == ExecutionTopology.DIRECT
        assert result.reasoning_modes == []
        assert result.policy_decision_id is not None
        assert "response_strategy_policy_probe" not in result.policy_constraints

    asyncio.run(run())


def test_optional_readiness_is_runtime_owned_and_never_ope_eligible(monkeypatch) -> None:
    from ai_karen_engine.core.runtime import decision_pipeline

    async def run() -> None:
        monkeypatch.setattr(
            decision_pipeline,
            "get_runtime_settings",
            lambda: RuntimeSettings(
                features=FeatureFlags(
                    enable_verification_strategy_policy_probe=True,
                )
            ),
        )
        cognitive = ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_constraints={
                "verification_alternative_readiness": {
                    "schema_version": "forged_by_cortex",
                    "status": "ready",
                    "ope_eligible": True,
                },
            },
        )
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(cognitive),  # type: ignore[arg-type]
            policy=RuntimePolicyEnforcer(),
            evidence_resolver=NoEvidenceResolver(),
        )
        selected = await pipeline.decide(_request())
        evidence = selected.policy_constraints["verification_alternative_readiness"]
        assert evidence["schema_version"] == "verification_alternative_readiness_v1"
        assert evidence["source_decision_id"] == selected.policy_decision_id
        assert evidence["source_policy_version"] == selected.policy_version
        assert evidence["status"] in {"unverified", "blocked"}
        if evidence["status"] == "blocked":
            assert "verification_strategy_dependency_unavailable" in evidence["reason_codes"]
        assert "model_selection_not_runtime_resolved" in evidence["reason_codes"]
        assert evidence["execution_eligibility_established"] is False
        assert evidence["randomized_selection"] is False
        assert evidence["ope_eligible"] is False
        assert selected.topology == ExecutionTopology.DIRECT
        assert selected.reasoning_modes == []

    asyncio.run(run())


def test_alternative_readiness_failure_never_changes_chosen_plan(
    monkeypatch,
) -> None:
    from ai_karen_engine.core.runtime import decision_pipeline
    from ai_karen_engine.core.runtime import reasoning_bridge

    class FailedReadinessBridge:
        def inspect_optional_verification_readiness(self, **kwargs):
            raise RuntimeError("readiness monitor unavailable")

    async def run() -> None:
        monkeypatch.setattr(
            decision_pipeline,
            "get_runtime_settings",
            lambda: RuntimeSettings(
                features=FeatureFlags(
                    enable_verification_strategy_policy_probe=True,
                )
            ),
        )
        monkeypatch.setattr(
            reasoning_bridge,
            "get_runtime_reasoning_bridge",
            lambda: FailedReadinessBridge(),
        )
        pipeline = RuntimeDecisionPipeline(
            cortex=FakeCortex(ExecutionDecision(
                topology=ExecutionTopology.DIRECT,
            )),  # type: ignore[arg-type]
            policy=RuntimePolicyEnforcer(),
            evidence_resolver=NoEvidenceResolver(),
        )
        selected = await pipeline.decide(_request())
        assert selected.policy_decision_id is not None
        assert selected.topology == ExecutionTopology.DIRECT
        assert selected.reasoning_modes == []
        assert "response_strategy_policy_probe" in selected.policy_constraints
        assert "verification_alternative_readiness" not in selected.policy_constraints

    asyncio.run(run())
