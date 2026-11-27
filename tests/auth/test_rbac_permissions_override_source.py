"""RBAC override diagnostics must not silently change authorization source."""

from __future__ import annotations

import json

import pytest

from ai_karen_engine.auth import rbac_middleware as rbac


def test_override_is_authoritative_and_role_names_are_not_permissions(
    tmp_path, monkeypatch, caplog
):
    path = tmp_path / "permissions.json"
    path.write_text(json.dumps({"roles": {"user": {"permissions": ["admin", "user", "read"]}}}))
    monkeypatch.setenv("KARI_PERMISSIONS_CONFIG", str(path))
    monkeypatch.delenv("PERMISSIONS_CONFIG_PATH", raising=False)
    rbac._load_permissions_config.cache_clear()
    try:
        config = rbac._load_permissions_config()
        assert config["roles"]["user"]["permissions"] == ["admin", "user", "read"]
        permissions = rbac._resolve_permission_names(config["roles"]["user"]["permissions"])
        assert permissions == {rbac.Permission.READ}
        assert "configured override" in caplog.text
    finally:
        rbac._load_permissions_config.cache_clear()


def test_missing_explicit_override_fails_without_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("KARI_PERMISSIONS_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.delenv("PERMISSIONS_CONFIG_PATH", raising=False)
    rbac._load_permissions_config.cache_clear()
    try:
        with pytest.raises(FileNotFoundError, match="unavailable"):
            rbac._load_permissions_config()
    finally:
        rbac._load_permissions_config.cache_clear()


def test_invalid_override_fails_without_fallback(tmp_path, monkeypatch):
    path = tmp_path / "permissions.json"
    path.write_text("{invalid json")
    monkeypatch.setenv("KARI_PERMISSIONS_CONFIG", str(path))
    rbac._load_permissions_config.cache_clear()
    try:
        with pytest.raises(ValueError, match="invalid"):
            rbac._load_permissions_config()
    finally:
        rbac._load_permissions_config.cache_clear()


def test_owner_explorer_permissions_are_narrow_and_configurable():
    from ai_karen_engine.auth.models import UserData

    manager = rbac.get_rbac_manager()
    user = UserData(user_id="owner", tenant_id="tenant", roles=["user"])
    readonly = UserData(user_id="reader", tenant_id="tenant", roles=["readonly"])
    assert manager.has_permission(user, rbac.Permission.FILE_EXPLORER_ORGANIZE)
    assert manager.has_permission(user, rbac.Permission.FILE_EXPLORER_DELETE_EMPTY)
    assert not manager.has_permission(user, rbac.Permission.DATA_WRITE)
    assert not manager.has_permission(user, rbac.Permission.DATA_DELETE)
    assert not manager.has_permission(readonly, rbac.Permission.FILE_EXPLORER_ORGANIZE)
    assert not manager.has_permission(readonly, rbac.Permission.FILE_EXPLORER_DELETE_EMPTY)
