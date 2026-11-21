"""WS-04A9E: general RuntimePolicy requests never issue author consent.

Author-issued document rights require an authenticated, deliberate and
source-scoped host approval, not caller-controlled policy request fields.
"""
from __future__ import annotations

import uuid

import pytest

from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    PolicyReasonCode,
    RuntimePolicyEnforcer,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("action", [
    "writing_style.document_consent.issue",
    "writing_style.document_consent.revoke",
    "writing_style.document_consent.renew",
])
async def test_general_policy_request_cannot_approve_author_consent(action):
    enforcer = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        user_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        action=action,
        requested_capabilities=[action],
        permissions=[action],
        roles=["admin"],
    )
    decision = await enforcer.evaluate(request)
    assert decision.allowed is False
    assert decision.requires_human_gate is True
    assert PolicyReasonCode.INSUFFICIENT_PERMISSION in decision.reason_codes
    assert action in decision.denied_capabilities


async def test_generic_action_cannot_smuggle_consent_through_capability():
    cap = "writing_style.document_consent.issue"
    decision = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id=str(uuid.uuid4()),
            tenant_id=str(uuid.uuid4()),
            action="general_assist",
            requested_capabilities=[cap],
            permissions=[cap],
        )
    )
    assert decision.allowed is False
    assert cap in decision.denied_capabilities


async def test_absent_principal_never_approves_author_consent():
    action = "writing_style.document_consent.issue"
    decision = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="",
            tenant_id="",
            action=action,
            requested_capabilities=[action],
            permissions=[action],
        )
    )
    assert decision.allowed is False
