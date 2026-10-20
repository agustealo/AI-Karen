"""Planner permissions are governed by canonical RBAC, not generic data grants."""

from uuid import uuid4

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager


def user_with(*, roles=None, permissions=None):
    return UserData(
        user_id=str(uuid4()), tenant_id=str(uuid4()),
        roles=list(roles or []), permissions=list(permissions or []),
    )


def test_standard_user_has_personal_planner_permissions():
    manager = get_rbac_manager()
    principal = user_with(roles=["user"])
    assert manager.has_permission(principal, Permission.PLANNER_READ)
    assert manager.has_permission(principal, Permission.PLANNER_WRITE)


def test_generic_data_read_and_write_do_not_grant_planner_access():
    manager = get_rbac_manager()
    principal = user_with(
        permissions=[Permission.DATA_READ.value, Permission.DATA_WRITE.value],
    )
    assert not manager.has_permission(principal, Permission.PLANNER_READ)
    assert not manager.has_permission(principal, Permission.PLANNER_WRITE)


def test_read_only_principal_cannot_edit_personal_planner():
    manager = get_rbac_manager()
    principal = user_with(roles=["readonly"])
    assert not manager.has_permission(principal, Permission.PLANNER_WRITE)


def test_explicit_planner_grant_works_without_broad_data_permission():
    manager = get_rbac_manager()
    principal = user_with(permissions=[Permission.PLANNER_READ.value])
    assert manager.has_permission(principal, Permission.PLANNER_READ)
    assert not manager.has_permission(principal, Permission.PLANNER_WRITE)


def test_effective_permission_asset_grants_planner_access_to_users():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    config = json.loads((root / "config_assets/permissions.json").read_text())
    for role in ("user", "admin"):
        permissions = config["role_permissions"][role]["permissions"]
        assert Permission.PLANNER_READ.value in permissions
        assert Permission.PLANNER_WRITE.value in permissions
