from pathlib import Path

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.models import orchestrator
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.automation.contracts import FlowType


ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / "src/ai_karen_engine/api_routes/models/orchestrator.py"


def test_deep_flow_route_has_no_client_identity_or_process_local_status_authority():
    source = ROUTE.read_text(encoding="utf-8")

    for forbidden in (
        "_flow_status_store",
        'headers.get("x-user-id")',
        'headers.get("x-tenant-id")',
        '@router.get("/flow-status/',
        '@router.post("/cancel-flow")',
        "CancelFlowRequest",
        "FlowStatusResponse",
    ):
        assert forbidden not in source

    assert "from ai_karen_engine.auth.session import get_current_user" in source
    assert "user: UserData = Depends(get_current_user)" in source
    assert 'context.pop("user_id", None)' in source
    assert 'context.pop("tenant_id", None)' in source


def test_flow_input_uses_authenticated_user_and_tenant_over_client_payload():
    request = orchestrator.ProcessFlowRequest(
        flow_type=FlowType.DECIDE_ACTION,
        prompt="route this request",
        user_id="spoofed-user",
        context={
            "user_id": "spoofed-context-user",
            "tenant_id": "spoofed-tenant",
            "trace": "keep-me",
        },
    )
    user = UserData(user_id="real-user", tenant_id="real-tenant")

    flow_input = orchestrator._build_flow_input_from_request(
        request_body=request,
        user=user,
        request_id="request-1",
        correlation_id="correlation-1",
    )

    assert flow_input["user_id"] == "real-user"
    assert flow_input["context"]["user_id"] == "real-user"
    assert flow_input["context"]["tenant_id"] == "real-tenant"
    assert flow_input["context"]["trace"] == "keep-me"
    assert flow_input["context"]["request_id"] == "request-1"
    assert flow_input["context"]["correlation_id"] == "correlation-1"


@pytest.mark.parametrize(
    "user",
    [
        UserData(user_id="", tenant_id="real-tenant"),
        UserData(user_id="real-user", tenant_id=""),
        UserData(user_id="real-user", tenant_id="default"),
    ],
)
def test_flow_input_fails_closed_without_explicit_authenticated_scope(user):
    request = orchestrator.ProcessFlowRequest(
        flow_type=FlowType.DECIDE_ACTION,
        prompt="route this request",
    )

    with pytest.raises(HTTPException):
        orchestrator._build_flow_input_from_request(
            request_body=request,
            user=user,
            request_id="request-1",
            correlation_id="correlation-1",
        )
