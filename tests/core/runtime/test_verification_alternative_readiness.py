"""KCOG-01C1B2A: a policy permission must never become execution proof."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
    RiskLevel,
)
from ai_karen_engine.core.runtime.policy import ResponseStrategyPolicyProbe
from ai_karen_engine.core.runtime.reasoning_bridge import (
    RuntimeReasoningBridge,
)


class ReadOnlyRegistry:
    """Record calls to the canonical read interfaces; no provider operation."""

    def __init__(
        self,
        *,
        registered: bool = True,
        model_registered: bool = True,
        health: str = "healthy",
    ) -> None:
        self.registered = registered
        self.model_registered = model_registered
        self.health = health
        self.calls: list[str] = []
        self.health_monitor = SimpleNamespace(
            get_provider_health=self.get_provider_health,
        )

    def canonicalize_provider_id(self, provider_id: str) -> str:
        self.calls.append("canonicalize")
        return provider_id.lower()

    def get_all_provider_names(self) -> list[str]:
        self.calls.append("inventory")
        return ["local-provider"] if self.registered else []

    def get_provider_health(self, provider_id: str) -> SimpleNamespace:
        self.calls.append("observed_health")
        return SimpleNamespace(
            health_status=SimpleNamespace(value=self.health),
            last_checked_at=datetime.utcnow(),
        )

    def is_model_available(
        self, provider_id: str, model: str, *, healthy_only: bool,
    ) -> bool:
        self.calls.append("model_inventory")
        assert healthy_only is False
        return self.model_registered


def _permission() -> ResponseStrategyPolicyProbe:
    return ResponseStrategyPolicyProbe(
        source_decision_id="policy-selected",
        source_policy_version="v2",
        selected_action="respond_direct",
        policy_permitted_actions=("respond_direct", "verify_then_respond"),
        status="alternative_reasoning_mode_policy_permitted",
        alternative_policy_decision_id="policy-alternative",
        alternative_policy_version="v2",
    )


def _decision() -> ExecutionDecision:
    return ExecutionDecision(
        topology=ExecutionTopology.DIRECT,
        policy_decision_id="policy-selected",
        policy_version="v2",
        risk_level=RiskLevel.LOW,
        max_model_calls=10,
        max_steps=10,
        time_budget_ms=30000,
        token_budget=4096,
    )


def _inspect(
    *,
    permission: ResponseStrategyPolicyProbe | None = None,
    decision: ExecutionDecision | None = None,
    provider: str | None = "local-provider",
    model: str | None = "local-model",
    registry: ReadOnlyRegistry | None = None,
):
    return RuntimeReasoningBridge().inspect_optional_verification_readiness(
        permission=permission or _permission(),
        decision=decision or _decision(),
        preferred_provider=provider,
        preferred_model=model,
        provider_registry=registry or ReadOnlyRegistry(),
    )


def test_observed_healthy_model_and_verifier_still_not_executable_evidence() -> None:
    registry = ReadOnlyRegistry()
    readiness = _inspect(registry=registry)
    assert readiness.status == "unverified"
    assert readiness.verifier_strategy_id == "verify"
    assert readiness.verifier_strategy_version == "v1"
    assert readiness.provider_health == "healthy"
    assert readiness.model_in_registered_inventory is True
    assert "verification_strategy_nongenerative" in readiness.reason_codes
    assert "complete_alternative_execution_not_observed" in readiness.reason_codes
    assert registry.calls == [
        "canonicalize", "inventory", "observed_health", "model_inventory",
    ]
    metadata = readiness.to_metadata()
    assert metadata["execution_eligibility_established"] is False
    assert metadata["randomized_selection"] is False
    assert metadata["ope_eligible"] is False
    assert "candidate_probabilities" not in metadata
    assert "model" not in metadata


@pytest.mark.parametrize(
    "probe,decision",
    [
        (replace(_permission(), status="selected_only"), _decision()),
        (replace(_permission(), source_decision_id="foreign"), _decision()),
        (replace(_permission(), alternative_policy_version="old"), _decision()),
        (_permission(), replace(_decision(), risk_level=RiskLevel.HIGH)),
        (_permission(), replace(_decision(), tool_requirements=["web"])),
        (_permission(), replace(_decision(), plugin_candidates=["private"])),
        (_permission(), replace(_decision(), requires_human_gate=True)),
        (_permission(), replace(_decision(), reasoning_modes=["verification"])),
        (_permission(), replace(_decision(), policy_version="wrong")),
    ],
)
def test_non_permitted_or_misaligned_decisions_do_not_inspect_provider(
    probe: ResponseStrategyPolicyProbe, decision: ExecutionDecision,
) -> None:
    registry = ReadOnlyRegistry()
    readiness = _inspect(permission=probe, decision=decision, registry=registry)
    assert readiness.status == "not_permitted"
    assert readiness.reason_codes == ("alternative_policy_or_plan_not_authorized",)
    assert registry.calls == []
    assert readiness.to_metadata()["ope_eligible"] is False


@pytest.mark.parametrize("budget_change", [
    {"max_model_calls": 1},
    {"max_steps": 0},
    {"time_budget_ms": 0},
    {"token_budget": 0},
])
def test_budget_insufficient_blocks_readiness(budget_change: dict) -> None:
    readiness = _inspect(decision=replace(_decision(), **budget_change))
    assert readiness.status == "blocked"
    assert "insufficient_authorized_execution_budget" in readiness.reason_codes


@pytest.mark.parametrize("provider,model", [
    (None, None), ("auto", "local-model"), ("local-provider", "auto"),
])
def test_unresolved_selected_model_does_not_trigger_provider_lookup(
    provider: str | None, model: str | None,
) -> None:
    registry = ReadOnlyRegistry()
    readiness = _inspect(provider=provider, model=model, registry=registry)
    assert readiness.status == "unverified"
    assert "model_selection_not_runtime_resolved" in readiness.reason_codes
    assert registry.calls == []


def test_unregistered_provider_is_blocked_not_assumed_healthy() -> None:
    registry = ReadOnlyRegistry(registered=False)
    readiness = _inspect(registry=registry)
    assert readiness.status == "blocked"
    assert "provider_not_registered" in readiness.reason_codes
    assert registry.calls == ["canonicalize", "inventory"]


@pytest.mark.parametrize("health", ["unhealthy", "unavailable"])
def test_authoritatively_bad_health_blocks_alternative(health: str) -> None:
    readiness = _inspect(registry=ReadOnlyRegistry(health=health))
    assert readiness.status == "blocked"
    assert "provider_observed_unavailable" in readiness.reason_codes


@pytest.mark.parametrize("health", ["unknown", "degraded"])
def test_unverified_health_never_becomes_ready(health: str) -> None:
    readiness = _inspect(registry=ReadOnlyRegistry(health=health))
    assert readiness.status == "unverified"
    assert "provider_health_unverified" in readiness.reason_codes


def test_unlisted_model_is_unknown_not_invented_unavailable() -> None:
    readiness = _inspect(registry=ReadOnlyRegistry(model_registered=False))
    assert readiness.status == "unverified"
    assert readiness.model_in_registered_inventory is False
    assert "model_inventory_unverified" in readiness.reason_codes
