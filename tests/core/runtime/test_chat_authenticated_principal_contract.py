"""Trusted ingress principal is necessary for governed planner access."""

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext


def test_matching_authenticated_ingress_identity_is_available_to_runtime():
    user = UserData(user_id="user-a", tenant_id="tenant-a")
    context = ChatExecutionContext(
        user_id="user-a", tenant_id="tenant-a", authenticated_user=user,
    )
    assert context.require_authenticated_user() is user
    assert "authenticated_user" not in repr(context)


@pytest.mark.parametrize("context", [
    ChatExecutionContext(user_id="user-a", tenant_id="tenant-a"),
    ChatExecutionContext(user_id="user-a", tenant_id="tenant-a",
                         authenticated_user=UserData(user_id="other", tenant_id="tenant-a")),
    ChatExecutionContext(user_id="user-a", tenant_id="tenant-a",
                         authenticated_user=UserData(user_id="user-a", tenant_id="other")),
    ChatExecutionContext(user_id="user-a", tenant_id="tenant-a",
                         authenticated_user=UserData(user_id="user-a", tenant_id="tenant-a", is_active=False)),
    ChatExecutionContext(user_id="user-a", tenant_id="tenant-a",
                         authenticated_user=UserData(user_id="user-a", tenant_id="tenant-a", is_verified=False)),
])
def test_missing_mismatched_or_inactive_principal_cannot_authorize_planner(context):
    with pytest.raises(PermissionError):
        context.require_authenticated_user()
