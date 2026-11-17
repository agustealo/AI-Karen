"""KPLUG-CONV-02C1: generic policy requests never mint lifecycle grants."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["plugin.lifecycle.enable", "plugin.lifecycle.disable"])
@pytest.mark.parametrize("surface", ["action", "capability", "mixed"])
async def test_generic_runtime_policy_refuses_plugin_lifecycle_authority(
    action: str,
    surface: str,
) -> None:
    request = PolicyEvaluationRequest(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="session-1",
        roles=["admin"],
        permissions=["admin", "admin.plugins:manage"],
        action=action if surface == "action" else "general_assist",
        requested_capabilities=(
            [action, "plugin.inspect"] if surface == "mixed"
            else [action] if surface == "capability" else []
        ),
        plugin_id="timezone-clock",
    )

    decision = await RuntimePolicyEnforcer().evaluate(request)

    assert decision.allowed is False
    assert decision.requires_human_gate is True
    assert decision.risk_level == "high"
    assert decision.allowed_capabilities == []
    assert "insufficient_permission" in [item.value for item in decision.reason_codes]


@pytest.mark.asyncio
async def test_unknown_lifecycle_verb_is_not_an_authority_escape() -> None:
    decision = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="11111111-1111-1111-1111-111111111111",
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            action="plugin.lifecycle.reinstall",
            requested_capabilities=["plugin.inspect"],
            roles=["admin"],
            permissions=["admin", "admin.plugins:manage"],
        )
    )
    assert not decision.allowed
    assert not decision.allowed_capabilities
