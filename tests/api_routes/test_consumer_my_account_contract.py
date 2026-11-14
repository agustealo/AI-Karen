"""Consumer account ingress must verify canonical owner and tenant truth."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ai_karen_engine.api_routes.auth import auth as auth_routes
from ai_karen_engine.auth.models import UserData


USER_ID = "11111111-1111-1111-1111-111111111111"
TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def principal(tenant_id: str = TENANT_A) -> UserData:
    return UserData(
        user_id=USER_ID,
        tenant_id=tenant_id,
        email="member@example.org",
        roles=["user"],
    )


class AccountService:
    def __init__(self, tenant_id: str = TENANT_A) -> None:
        self.account = SimpleNamespace(
            id=USER_ID,
            tenant_id=tenant_id,
            email="member@example.org",
            username="member",
            full_name="Member One",
            roles=["user"],
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            last_login=None,
            preferences={
                "theme": "dark",
                "notifications": {"enabled": False},
            },
        )
        self.profile_calls: list[dict[str, Any]] = []
        self.password_calls: list[tuple[str, str, str]] = []
        self.password_error: str | None = None

    async def get_user_by_id(self, user_id: str):
        return self.account if user_id == USER_ID else None

    async def update_user_profile(self, user_id: str, **changes: Any):
        self.profile_calls.append({"user_id": user_id, **changes})
        for key in ("email", "username", "full_name"):
            if changes.get(key) is not None:
                setattr(self.account, key, changes[key])
        if changes.get("preferences") is not None:
            self.account.preferences = {
                **self.account.preferences,
                **changes["preferences"],
            }
        return self.account, None

    async def change_user_password(self, user_id: str, current: str, new: str):
        self.password_calls.append((user_id, current, new))
        return self.password_error


@pytest.mark.asyncio
async def test_account_read_returns_canonical_owned_profile() -> None:
    service = AccountService()
    result = await auth_routes.get_current_user_info(
        current_user=principal(),
        auth_svc=service,
    )
    assert result["tenant_id"] == TENANT_A
    assert result["user_id"] == USER_ID
    assert result["authenticated"] is True
    assert result["preferences"]["notifications"]["enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "profile", "password"])
async def test_account_ingress_rejects_stale_tenant_before_any_mutation(
    operation: str,
) -> None:
    service = AccountService(tenant_id=TENANT_B)

    with pytest.raises(HTTPException) as error:
        if operation == "read":
            await auth_routes.get_current_user_info(principal(), service)
        elif operation == "profile":
            await auth_routes.update_current_user_info(
                auth_routes.UpdateProfileRequest(full_name="New Name"),
                current_user=principal(),
                auth_svc=service,
            )
        else:
            await auth_routes.change_password(
                auth_routes.ChangePasswordRequest(
                    current_password="OldSecret#123",
                    new_password="NewSecret#123",
                    confirm_password="NewSecret#123",
                ),
                current_user=principal(),
                auth_svc=service,
            )

    assert error.value.status_code == 401
    assert service.profile_calls == []
    assert service.password_calls == []


@pytest.mark.asyncio
async def test_account_theme_write_preserves_unrelated_canonical_preferences() -> None:
    service = AccountService()
    changed = await auth_routes.update_current_user_info(
        auth_routes.UpdateProfileRequest(preferences={"theme": "system"}),
        current_user=principal(),
        auth_svc=service,
    )

    assert changed["preferences"]["theme"] == "system"
    assert changed["preferences"]["notifications"] == {"enabled": False}
    assert service.profile_calls == [{
        "user_id": USER_ID,
        "email": None,
        "username": None,
        "full_name": None,
        "preferences": {"theme": "system"},
    }]


@pytest.mark.asyncio
async def test_account_profile_normalizes_fields_without_cross_scope_write() -> None:
    service = AccountService()
    updated = await auth_routes.update_current_user_info(
        auth_routes.UpdateProfileRequest(
            username="  named-member  ",
            full_name="  Member Two ",
            email=" MEMBER2@EXAMPLE.ORG ",
        ),
        current_user=principal(),
        auth_svc=service,
    )
    assert updated["username"] == "named-member"
    assert updated["full_name"] == "Member Two"
    assert updated["email"] == "member2@example.org"
    assert updated["tenant_id"] == TENANT_A


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": "   "},
        {"username": "bad username"},
        {"email": "not-an-email"},
        {"email": " "},
        {},
    ],
)
def test_account_profile_rejects_invalid_fields(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        auth_routes.UpdateProfileRequest(**payload)


@pytest.mark.asyncio
async def test_incorrect_password_does_not_invalidate_authenticated_session() -> None:
    service = AccountService()
    service.password_error = "Current password is incorrect"

    with pytest.raises(HTTPException) as error:
        await auth_routes.change_password(
            auth_routes.ChangePasswordRequest(
                current_password="WrongPassword#1",
                new_password="AnotherSecret#2",
                confirm_password="AnotherSecret#2",
            ),
            current_user=principal(),
            auth_svc=service,
        )

    assert error.value.status_code == 400
    assert service.password_calls == [(USER_ID, "WrongPassword#1", "AnotherSecret#2")]


@pytest.mark.asyncio
async def test_successful_password_change_uses_same_authenticated_owner() -> None:
    service = AccountService()
    response = await auth_routes.change_password(
        auth_routes.ChangePasswordRequest(
            current_password="CurrentSecret#1",
            new_password="AnotherSecret#2",
            confirm_password="AnotherSecret#2",
        ),
        current_user=principal(),
        auth_svc=service,
    )
    assert response.status_code == 200
    assert service.password_calls == [(USER_ID, "CurrentSecret#1", "AnotherSecret#2")]
