"""Tests for the authentication compatibility facade."""

from __future__ import annotations

import importlib.util
import inspect
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"


def _patch_broken_imports():
    pm = types.ModuleType("ai_karen_engine.core.observability.performance_metrics")
    pm.MetricType = str  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.observability.performance_metrics"] = pm

    ctx = types.ModuleType("ai_karen_engine.core.observability.context")
    ctx.ObservabilityContext = object  # type: ignore[attr-defined]
    ctx.get_observability_context = lambda: None  # type: ignore[attr-defined]
    ctx.bind_observability_context = lambda *a, **kw: None  # type: ignore[attr-defined]
    ctx.clear_observability_context = lambda: None  # type: ignore[attr-defined]
    ctx.set_observability_context = lambda *a, **kw: None  # type: ignore[attr-defined]
    ctx.configure_runtime_logging = lambda *a, **kw: None  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.observability.context"] = ctx

    obs_init = types.ModuleType("ai_karen_engine.core.observability")
    obs_init.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.observability"] = obs_init

    log = types.ModuleType("ai_karen_engine.core.logging")
    log.__path__ = []  # type: ignore[attr-defined]
    log.get_logger = lambda name: __import__("logging").getLogger(name)  # type: ignore[attr-defined]
    log.get_structured_logger = lambda name: __import__("logging").getLogger(name)  # type: ignore[attr-defined]
    log.configure_runtime_logging = lambda *a, **kw: None  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.logging"] = log

    sec_init = types.ModuleType("ai_karen_engine.core.security")
    sec_init.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.security"] = sec_init

    sec_mod = types.ModuleType("ai_karen_engine.core.security.security")
    sec_mod.__path__ = []  # type: ignore[attr-defined]
    sec_mod.SecurityLevel = object  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.security.security"] = sec_mod

    enc = types.ModuleType("ai_karen_engine.core.security.encryption_utils")
    enc.__path__ = []  # type: ignore[attr-defined]
    enc.encrypt_data = lambda *a, **kw: b""  # type: ignore[attr-defined]
    enc.decrypt_data = lambda *a, **kw: b""  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.security.encryption_utils"] = enc

    svc_init = types.ModuleType("ai_karen_engine.core.services")
    svc_init.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.services"] = svc_init

    base = types.ModuleType("ai_karen_engine.core.services.base")
    base.__path__ = []  # type: ignore[attr-defined]
    base.BaseService = object  # type: ignore[attr-defined]
    base.ServiceConfig = object  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.core.services.base"] = base

    db = types.ModuleType("ai_karen_engine.database")
    db.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.database"] = db

    db_client = types.ModuleType("ai_karen_engine.database.client")
    db_client.__path__ = []  # type: ignore[attr-defined]
    db_client.MultiTenantPostgresClient = object  # type: ignore[attr-defined]
    db_client.get_db_session_context = lambda: None  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.database.client"] = db_client

    db_models = types.ModuleType("ai_karen_engine.database.models")
    db_models.__path__ = []  # type: ignore[attr-defined]
    db_models.AuthUser = object  # type: ignore[attr-defined]
    db_models.AuthSession = object  # type: ignore[attr-defined]
    db_models.Tenant = object  # type: ignore[attr-defined]
    db_models.Base = object  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.database.models"] = db_models

    cm = types.ModuleType("ai_karen_engine.config.config_manager")
    cm.__path__ = []  # type: ignore[attr-defined]
    cm.get_config = lambda: None  # type: ignore[attr-defined]
    cm.resolve_jwt_secret = lambda: ""  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.config.config_manager"] = cm

    mid = types.ModuleType("ai_karen_engine.middleware")
    mid.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.middleware"] = mid

    mid_init = types.ModuleType("ai_karen_engine.middleware.__init__")
    mid_init.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.middleware.__init__"] = mid_init

    ec = types.ModuleType("ai_karen_engine.middleware.error_counter")
    ec.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.middleware.error_counter"] = ec

    authz = types.ModuleType("ai_karen_engine.middleware.authorization_checker")
    authz.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.middleware.authorization_checker"] = authz

    usage = types.ModuleType("ai_karen_engine.services.usage")
    usage.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.services.usage"] = usage

    usage_svc = types.ModuleType("ai_karen_engine.services.usage.service")
    usage_svc.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.services.usage.service"] = usage_svc

    auth_svc = types.ModuleType("ai_karen_engine.services.auth.authorization_service")
    auth_svc.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.services.auth.authorization_service"] = auth_svc

    dps = types.ModuleType("ai_karen_engine.services.auth.data_protection_service")
    dps.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.services.auth.data_protection_service"] = dps

    us = types.ModuleType("ai_karen_engine.services.auth.user_service")
    us.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.services.auth.user_service"] = us

    ti = types.ModuleType("ai_karen_engine.services.auth.tenant_isolation")
    ti.__path__ = []  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.services.auth.tenant_isolation"] = ti

    svc_auth = types.ModuleType("ai_karen_engine.services.auth")
    svc_auth.__path__ = ["F:/KIRO/AI-Karen/src/ai_karen_engine/services/auth"]  # type: ignore[attr-defined]
    sys.modules["ai_karen_engine.services.auth"] = svc_auth


_patch_broken_imports()


def _load_facade_module():
    spec = importlib.util.spec_from_file_location(
        "ai_karen_engine.auth.auth_service",
        SRC / "ai_karen_engine" / "auth" / "auth_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


facade_module = _load_facade_module()
FacadeAuthService = facade_module.AuthService
CoreAuthService = facade_module.CoreAuthService
UserAccount = facade_module.UserAccount


def _user(**kwargs: Any) -> "UserAccount":
    defaults = dict(
        id="user-1",
        email="user@example.com",
        username="user",
        full_name="User",
        password_hash="",
        roles=[],
        status=kwargs.pop("status", None),
        is_verified=kwargs.pop("is_verified", True),
        two_factor_enabled=False,
        two_factor_secret=None,
        password_changed_at=None,
        last_login=None,
        created_at=kwargs.pop("created_at", None),
        updated_at=kwargs.pop("updated_at", None),
        locked_until=None,
        failed_login_attempts=0,
        preferences={},
        tenant_id="default",
        metadata={},
    )
    defaults.update(kwargs)
    if defaults["status"] is None:
        defaults["status"] = UserAccount.__dataclass_fields__["status"].default  # type: ignore[index]
    return UserAccount(**defaults)


class TestFacadeNeverAccessesPrivateServiceMembers:
    """The facade must only call public methods on the canonical service."""

    _forbidden_names = {
        "_session_scope",
        "_build_user_account",
        "_user_cache",
        "_active_sessions",
        "_load_config_from_env",
        "_validate_config",
        "_ensure_database_tables",
    }

    def test_facade_methods_expose_no_private_attributes(self):
        facade = FacadeAuthService()
        public_methods = [
            name
            for name, _ in inspect.getmembers(facade, predicate=inspect.ismethod)
            if not name.startswith("_")
        ]

        for method_name in public_methods:
            source = inspect.getsource(getattr(facade, method_name))
            for forbidden in self._forbidden_names:
                assert forbidden not in source, (
                    f"Facade.{method_name} references private member {forbidden}"
                )


class TestAdminUpdateDelegatesToAuthAuthority:
    """Admin updates must flow through the canonical AuthService."""

    @pytest.mark.asyncio
    async def test_update_user_delegates_to_canonical_service(self):
        fake_service = AsyncMock()
        fake_service.update_user = AsyncMock(
            return_value=_user(full_name="Admin User", roles=["admin"], preferences={"theme": "dark"})
        )

        facade = FacadeAuthService()
        facade._service = fake_service

        result = await facade.update_user(
            user_id="user-1",
            full_name="Admin User",
            roles=["admin"],
            preferences={"theme": "dark"},
            is_active=True,
            is_verified=True,
        )

        fake_service.update_user.assert_awaited_once_with(
            user_id="user-1",
            full_name="Admin User",
            roles=["admin"],
            preferences={"theme": "dark"},
            is_active=True,
            is_verified=True,
        )
        assert result["full_name"] == "Admin User"

    @pytest.mark.asyncio
    async def test_set_user_status_delegates_to_canonical_service(self):
        fake_service = AsyncMock()
        fake_service.set_user_status = AsyncMock(
            return_value=_user(status=__import__("ai_karen_engine.services.auth.auth_service", fromlist=["UserStatus"]).UserStatus.INACTIVE)
        )

        facade = FacadeAuthService()
        facade._service = fake_service

        result = await facade.set_user_status(
            user_id="user-1", is_active=False, reason="admin_action"
        )

        fake_service.set_user_status.assert_awaited_once_with(
            user_id="user-1", is_active=False, reason="admin_action"
        )
        assert result["status"] == {"value": "inactive"}

    @pytest.mark.asyncio
    async def test_set_user_roles_delegates_to_canonical_service(self):
        fake_service = AsyncMock()
        fake_service.set_user_roles = AsyncMock(
            return_value=_user(roles=["admin", "user"])
        )

        facade = FacadeAuthService()
        facade._service = fake_service

        result = await facade.set_user_roles(
            user_id="user-1", roles=["admin", "user"], reason="promotion"
        )

        fake_service.set_user_roles.assert_awaited_once_with(
            user_id="user-1", roles=["admin", "user"], reason="promotion"
        )
        assert result["roles"] == ["admin", "user"]

    @pytest.mark.asyncio
    async def test_update_user_preferences_delegates_to_canonical_service(self):
        fake_service = AsyncMock()
        fake_service.update_user_preferences = AsyncMock(
            return_value=_user(preferences={"lang": "fr"})
        )

        facade = FacadeAuthService()
        facade._service = fake_service

        result = await facade.update_user_preferences(
            user_id="user-1", preferences={"lang": "fr"}, merge=True
        )

        fake_service.update_user_preferences.assert_awaited_once_with(
            user_id="user-1", preferences={"lang": "fr"}, merge=True
        )
        assert result["preferences"] == {"lang": "fr"}


class TestFacadeDelegatesAuthentication:
    """Facade must delegate authentication flows to the canonical service."""

    @pytest.mark.asyncio
    async def test_authenticate_delegates(self):
        fake_service = AsyncMock()
        fake_user = _user(email="user@example.com", roles=["user"])
        fake_service.authenticate_user = AsyncMock(
            return_value=(fake_user, "access-token", "refresh-token")
        )

        facade = FacadeAuthService()
        facade._service = fake_service

        result = await facade.authenticate(
            "user@example.com", "password", ip_address="1.2.3.4", user_agent="test"
        )

        fake_service.authenticate_user.assert_awaited_once_with(
            email="user@example.com",
            password="password",
            ip_address="1.2.3.4",
            user_agent="test",
        )
        assert result["access_token"] == "access-token"

    @pytest.mark.asyncio
    async def test_verify_token_delegates(self):
        fake_service = AsyncMock()
        fake_service.validate_token = AsyncMock(
            return_value=_user(email="user@example.com")
        )

        facade = FacadeAuthService()
        facade._service = fake_service

        result = await facade.verify_token("valid-token")

        fake_service.validate_token.assert_awaited_once_with("valid-token")
        assert result["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_create_user_delegates(self):
        fake_service = AsyncMock()
        fake_service.create_user = AsyncMock(
            return_value=(
                _user(email="new@example.com"),
                None,
            )
        )

        facade = FacadeAuthService()
        facade._service = fake_service

        result = await facade.create_user(
            email="new@example.com",
            password="password123",
            full_name="New User",
            tenant_id="default",
            roles=["user"],
        )

        fake_service.create_user.assert_awaited_once()
        assert result["email"] == "new@example.com"
