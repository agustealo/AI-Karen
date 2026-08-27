from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.auth.auth_middleware import AuthenticationError, _explicit_tenant_id
from ai_karen_engine.auth.principal import (
    AuthenticatedPrincipal,
    build_principal_from_user_account,
)


def test_auth_tenant_helper_rejects_missing_and_default_scope() -> None:
    with pytest.raises(AuthenticationError):
        _explicit_tenant_id(None)
    with pytest.raises(AuthenticationError):
        _explicit_tenant_id("")
    with pytest.raises(AuthenticationError):
        _explicit_tenant_id("default")
    assert _explicit_tenant_id("tenant-a") == "tenant-a"


def test_trusted_principal_requires_explicit_tenant() -> None:
    with pytest.raises(ValueError, match="explicit non-default tenant_id"):
        AuthenticatedPrincipal(user_id="user-a", tenant_id="default")
    with pytest.raises(ValueError, match="explicit non-default tenant_id"):
        AuthenticatedPrincipal(user_id="user-a", tenant_id="")

    principal = AuthenticatedPrincipal(user_id="user-a", tenant_id="tenant-a")
    assert principal.tenant_id == "tenant-a"


def test_principal_builder_does_not_manufacture_default_tenant() -> None:
    with pytest.raises(ValueError, match="explicit non-default tenant_id"):
        build_principal_from_user_account(SimpleNamespace(id="user-a", roles=[]))

    principal = build_principal_from_user_account(
        SimpleNamespace(id="user-a", tenant_id="tenant-a", roles=["user"])
    )
    assert principal.tenant_id == "tenant-a"
