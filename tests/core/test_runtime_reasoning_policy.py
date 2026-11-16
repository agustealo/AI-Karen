from __future__ import annotations

import asyncio

from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimeLevel,
    RuntimePolicyEnforcer,
    SOFT_EXPLORATION_MIN_MODEL_CALLS,
    authorize_reasoning_modes,
)


def test_empty_request_stays_empty() -> None:
    result = authorize_reasoning_modes([])
    assert result.requested_modes == ()
    assert result.allowed_modes == ()
    assert result.denied_modes == ()


def test_aliases_are_canonicalized() -> None:
    result = authorize_reasoning_modes(["verify", "refine", "synthesis"])
    assert result.allowed_modes == (
        "verification",
        "refinement",
        "evidence_synthesis",
    )


def test_soft_exploration_requires_compute_budget() -> None:
    denied = authorize_reasoning_modes(
        ["soft_exploration"],
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS - 1,
    )
    allowed = authorize_reasoning_modes(
        ["soft_exploration"],
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS,
    )
    assert denied.denied_modes == ("soft_exploration",)
    assert denied.denial_reasons["soft_exploration"] == (
        "model_call_budget_insufficient",
    )
    assert allowed.allowed_modes == ("soft_exploration",)


def test_reduced_runtime_denies_soft_exploration() -> None:
    result = authorize_reasoning_modes(
        ["verification", "soft_exploration"],
        runtime_level="REDUCED",
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS,
    )
    assert result.allowed_modes == ("verification",)
    assert result.denied_modes == ("soft_exploration",)


def test_high_risk_preserves_verification_and_denies_exploration() -> None:
    result = authorize_reasoning_modes(
        ["verification", "counterfactual", "soft_exploration"],
        runtime_level="FULL",
        risk_level="high",
        max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS,
    )
    assert result.allowed_modes == ("verification",)
    assert result.denied_modes == ("counterfactual", "soft_exploration")


def test_emergency_runtime_allows_only_verification_and_evidence_synthesis() -> None:
    result = authorize_reasoning_modes(
        ["causal", "verification", "evidence_synthesis", "refinement"],
        runtime_level="EMERGENCY",
    )
    assert result.allowed_modes == ("verification", "evidence_synthesis")
    assert result.denied_modes == ("causal", "refinement")


def test_runtime_policy_returns_typed_allowed_and_denied_reasoning_modes() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        result = await policy.evaluate(
            PolicyEvaluationRequest(
                user_id="user-1",
                tenant_id="tenant-1",
                requested_reasoning_modes=["verification", "soft_exploration"],
                max_model_calls=SOFT_EXPLORATION_MIN_MODEL_CALLS - 1,
                runtime_level=RuntimeLevel.FULL,
            )
        )
        assert result.allowed is True
        assert result.allowed_reasoning_modes == ["verification"]
        assert result.denied_reasoning_modes == ["soft_exploration"]
        assert result.reasoning_denial_reasons["soft_exploration"] == [
            "model_call_budget_insufficient"
        ]

    asyncio.run(run())


def test_authorized_plan_uses_policy_reasoning_modes_not_requested_modes() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        result = await policy.evaluate(
            PolicyEvaluationRequest(
                user_id="user-1",
                tenant_id="tenant-1",
                requested_reasoning_modes=["verification", "soft_exploration"],
                max_model_calls=10,
                runtime_level=RuntimeLevel.FULL,
            )
        )
        plan = result.to_authorized_plan()
        assert plan.reasoning_modes == ["verification"]
        assert "soft_exploration" not in plan.reasoning_modes

    asyncio.run(run())


def test_policy_never_invents_reasoning_mode() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        result = await policy.evaluate(
            PolicyEvaluationRequest(
                user_id="user-1",
                tenant_id="tenant-1",
                requested_reasoning_modes=[],
                max_model_calls=100,
            )
        )
        assert result.allowed_reasoning_modes == []
        assert result.denied_reasoning_modes == []
        assert result.to_authorized_plan().reasoning_modes == []

    asyncio.run(run())


def test_optional_verification_probe_is_policy_permission_not_execution() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        request = PolicyEvaluationRequest(
            user_id="subject",
            tenant_id="tenant-a",
            session_id="session-a",
            requested_reasoning_modes=[],
            max_model_calls=10,
            runtime_level=RuntimeLevel.FULL,
        )
        selected = await policy.evaluate(request)
        original_modes = list(request.requested_reasoning_modes)
        probe = await policy.probe_optional_verification(
            request, selected, direct_plan_authorized=True,
        )

        assert selected.allowed is True
        assert selected.allowed_reasoning_modes == []
        assert request.requested_reasoning_modes == original_modes
        assert probe.policy_permitted_actions == (
            "respond_direct", "verify_then_respond",
        )
        assert probe.source_decision_id == selected.decision_id
        assert probe.source_policy_version == selected.policy_version
        assert probe.alternative_policy_decision_id != selected.decision_id
        assert probe.status == "alternative_reasoning_mode_policy_permitted"
        assert probe.to_metadata()["execution_eligibility_established"] is False
        assert probe.to_metadata()["randomized_selection"] is False
        assert probe.to_metadata()["ope_eligible"] is False

    asyncio.run(run())


def test_optional_verification_probe_rejects_unsafe_alternatives() -> None:
    async def run() -> None:
        policy = RuntimePolicyEnforcer()
        requests = [
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=1,
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10, runtime_level=RuntimeLevel.SAFE,
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10, risk_signals={"score": 0.7},
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10, tool_id="web",
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10,
                execution_topology={"plugin_candidates": ["private-tool"]},
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10,
                execution_topology={"agent_delegation": True},
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10,
                execution_topology={"requires_human_gate": True},
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10,
                requested_reasoning_modes=["verification"],
            ),
            PolicyEvaluationRequest(
                user_id="subject", tenant_id="tenant-a",
                max_model_calls=10,
                requested_capabilities=["model.personal_key.execute"],
            ),
        ]
        for request in requests:
            selected = await policy.evaluate(request)
            result = await policy.probe_optional_verification(
                request, selected, direct_plan_authorized=True,
            )
            assert result.policy_permitted_actions == (
                ("respond_direct",) if selected.allowed else ()
            )
            assert result.alternative_policy_decision_id is None
            assert result.to_metadata()["ope_eligible"] is False

        # The caller may never turn a denied CORTEX plan into proof.
        direct = requests[0]
        selected = await policy.evaluate(direct)
        rejected = await policy.probe_optional_verification(
            direct, selected, direct_plan_authorized=False,
        )
        assert rejected.status == "not_authorized"
        assert rejected.policy_permitted_actions == ()

    asyncio.run(run())


def test_optional_verification_probe_requires_independent_policy_grant() -> None:
    from dataclasses import replace

    class DenyAlternativePolicy(RuntimePolicyEnforcer):
        async def evaluate(self, request: PolicyEvaluationRequest):
            decision = await super().evaluate(request)
            if request.requested_reasoning_modes == ["verification"]:
                return replace(decision, allowed=False)
            return decision

    async def run() -> None:
        policy = DenyAlternativePolicy()
        request = PolicyEvaluationRequest(
            user_id="subject", tenant_id="tenant-a",
            session_id="session-a", max_model_calls=10,
        )
        selected = await policy.evaluate(request)
        result = await policy.probe_optional_verification(
            request, selected, direct_plan_authorized=True,
        )
        assert result.policy_permitted_actions == ("respond_direct",)
        assert result.alternative_policy_decision_id is None

    asyncio.run(run())


def test_policy_probe_feature_flag_is_default_off_and_strictly_configured(
    monkeypatch,
) -> None:
    import pytest

    from ai_karen_engine.config.runtime import RuntimeSettings

    settings = RuntimeSettings()
    assert settings.features.enable_verification_strategy_policy_probe is False
    monkeypatch.setenv("KARI_ENABLE_VERIFICATION_STRATEGY_POLICY_PROBE", "true")
    settings.apply_env_overrides()
    assert settings.features.enable_verification_strategy_policy_probe is True
    assert settings.validate() == []
    monkeypatch.setenv("KARI_ENABLE_VERIFICATION_STRATEGY_POLICY_PROBE", "off")
    settings.apply_env_overrides()
    assert settings.features.enable_verification_strategy_policy_probe is False
    monkeypatch.setenv("KARI_ENABLE_VERIFICATION_STRATEGY_POLICY_PROBE", "maybe")
    with pytest.raises(ValueError, match="must be a boolean"):
        settings.apply_env_overrides()
    monkeypatch.delenv("KARI_ENABLE_VERIFICATION_STRATEGY_POLICY_PROBE")
    settings.features.enable_verification_strategy_policy_probe = "true"
    assert any("policy probe flag must be boolean" in issue for issue in settings.validate())


def test_optional_policy_probe_cannot_accept_cross_principal_decision() -> None:
    from dataclasses import replace

    class SpoofedAlternativePolicy(RuntimePolicyEnforcer):
        async def evaluate(self, request: PolicyEvaluationRequest):
            decision = await super().evaluate(request)
            if request.requested_reasoning_modes == ["verification"]:
                return replace(
                    decision,
                    runtime_constraints={
                        **decision.runtime_constraints,
                        "authorized_tenant_id": "another-tenant",
                    },
                )
            return decision

    async def run() -> None:
        policy = SpoofedAlternativePolicy()
        request = PolicyEvaluationRequest(
            user_id="subject", tenant_id="tenant-a",
            session_id="session-a", max_model_calls=10,
        )
        selected = await policy.evaluate(request)
        probe = await policy.probe_optional_verification(
            request, selected, direct_plan_authorized=True,
        )
        assert probe.status == "selected_only"
        assert probe.policy_permitted_actions == ("respond_direct",)
        assert probe.alternative_policy_decision_id is None
        assert probe.to_metadata()["execution_eligibility_established"] is False

    asyncio.run(run())
