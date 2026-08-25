"""Tests for the canonical authentication authority."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SRC = Path(__file__).resolve().parents[3] / "src"


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


def _load_auth_service_module():
    spec = importlib.util.spec_from_file_location(
        "ai_karen_engine.services.auth.auth_service",
        SRC / "ai_karen_engine" / "services" / "auth" / "auth_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


auth_service_module = _load_auth_service_module()
AuthService = auth_service_module.AuthService
AuthConfig = auth_service_module.AuthConfig
load_auth_config = auth_service_module.load_auth_config
INSECURE_SECRET_MARKERS = auth_service_module.INSECURE_SECRET_MARKERS


def _load_principal_module():
    spec = importlib.util.spec_from_file_location(
        "ai_karen_engine.auth.principal",
        SRC / "ai_karen_engine" / "auth" / "principal.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


principal_module = _load_principal_module()
AuthenticatedPrincipal = principal_module.AuthenticatedPrincipal
build_principal_from_user_account = principal_module.build_principal_from_user_account

# Environment is defined in services/auth/config.py
config_spec = importlib.util.spec_from_file_location(
    "ai_karen_engine.services.auth.config",
    SRC / "ai_karen_engine" / "services" / "auth" / "config.py",
)
config_module = importlib.util.module_from_spec(config_spec)
sys.modules[config_spec.name] = config_module
config_spec.loader.exec_module(config_module)
Environment = config_module.Environment


class TestAuthConfigValidation:
    """AUTH-04 / AUTH-05: centralized config must fail closed in production."""

    def test_development_allows_insecure_secret(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "change-me-in-production")
        config = load_auth_config()
        assert config.environment == Environment.DEVELOPMENT
        assert config.jwt_secret_key == "change-me-in-production"

    def test_production_rejects_insecure_secret(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "change-me-in-production")
        with pytest.raises(RuntimeError, match="AUTH_JWT_SECRET_KEY must be set"):
            load_auth_config()

    def test_production_rejects_empty_secret(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("AUTH_JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="AUTH_JWT_SECRET_KEY must be set"):
            load_auth_config()

    def test_staging_rejects_insecure_secret(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "your-secret-key")
        with pytest.raises(RuntimeError, match="AUTH_JWT_SECRET_KEY must be set"):
            load_auth_config()

    def test_production_accepts_strong_secret(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "a-very-strong-secret-key-123!")
        config = load_auth_config()
        assert config.jwt_secret_key == "a-very-strong-secret-key-123!"

    def test_password_min_length_validation(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "strong-secret")
        monkeypatch.setenv("AUTH_PASSWORD_MIN_LENGTH", "4")
        with pytest.raises(RuntimeError, match="password_min_length must be at least 8"):
            load_auth_config()

    def test_max_failed_login_attempts_validation(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "strong-secret")
        monkeypatch.setenv("AUTH_MAX_FAILED_LOGIN_ATTEMPTS", "1")
        with pytest.raises(RuntimeError, match="max_failed_login_attempts must be at least 3"):
            load_auth_config()

    def test_bcrypt_rounds_validation(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("AUTH_JWT_SECRET_KEY", "strong-secret")
        monkeypatch.setenv("AUTH_BCRYPT_ROUNDS", "5")
        with pytest.raises(RuntimeError, match="bcrypt_rounds must be at least 10"):
            load_auth_config()


class TestAuthServicePublicApi:
    """AUTH-02: canonical service exposes public methods for all admin operations."""

    @pytest.fixture
    def auth_service(self):
        service = AuthService()
        service._initialized = True
        return service

    @pytest.mark.asyncio
    async def test_update_user_is_public(self, auth_service):
        auth_service._session_scope = AsyncMock()  # type: ignore[method-assign]
        mock_session = MagicMock()
        auth_service._session_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)  # type: ignore[attr-defined]
        auth_service._session_scope.return_value.__aexit__ = AsyncMock(return_value=False)  # type: ignore[attr-defined]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock(
            user_id="user-1",
            full_name="Old Name",
            roles=["user"],
            preferences={},
            is_active=True,
            is_verified=True,
            updated_at=datetime.utcnow(),
        )
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()

        user = await auth_service.update_user(
            user_id="user-1",
            full_name="New Name",
            roles=["admin"],
            preferences={"key": "value"},
            is_active=True,
            is_verified=True,
        )

        assert user.full_name == "New Name"
        assert user.roles == ["admin"]

    @pytest.mark.asyncio
    async def test_set_user_status_is_public(self, auth_service):
        auth_service.update_user = AsyncMock(  # type: ignore[method-assign]
            return_value=MagicMock(id="user-1")
        )
        auth_service._emit_audit_event = AsyncMock()  # type: ignore[method-assign]

        user = await auth_service.set_user_status("user-1", is_active=False, reason="admin_action")

        auth_service.update_user.assert_awaited_once_with(
            user_id="user-1", is_active=False
        )
        auth_service._emit_audit_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_user_roles_is_public(self, auth_service):
        auth_service.update_user = AsyncMock(  # type: ignore[method-assign]
            return_value=MagicMock(id="user-1")
        )
        auth_service._emit_audit_event = AsyncMock()  # type: ignore[method-assign]

        user = await auth_service.set_user_roles(
            "user-1", ["admin", "user"], reason="promotion"
        )

        auth_service.update_user.assert_awaited_once_with(
            user_id="user-1", roles=["admin", "user"]
        )
        auth_service._emit_audit_event.assert_awaited_once_with(
            action="auth.role.assigned",
            actor_user_id=None,
            target_user_id="user-1",
            status="success",
            reason_code="promotion",
            metadata={"roles": ["admin", "user"]},
        )

    @pytest.mark.asyncio
    async def test_update_user_preferences_merge(self, auth_service):
        existing_user = MagicMock(
            id="user-1",
            preferences={"theme": "dark", "lang": "en"},
        )
        auth_service.get_user_by_id = AsyncMock(return_value=existing_user)  # type: ignore[method-assign]
        auth_service.update_user = AsyncMock(  # type: ignore[method-assign]
            return_value=MagicMock(id="user-1", preferences={"theme": "light", "lang": "en"})
        )
        auth_service._emit_audit_event = AsyncMock()  # type: ignore[method-assign]

        user = await auth_service.update_user_preferences(
            "user-1", {"theme": "light"}, merge=True
        )

        auth_service.update_user.assert_awaited_once_with(
            user_id="user-1", preferences={"theme": "light", "lang": "en"}
        )

    @pytest.mark.asyncio
    async def test_update_user_preferences_replace(self, auth_service):
        auth_service.update_user = AsyncMock(  # type: ignore[method-assign]
            return_value=MagicMock(id="user-1", preferences={"only": "this"})
        )
        auth_service._emit_audit_event = AsyncMock()  # type: ignore[method-assign]

        user = await auth_service.update_user_preferences(
            "user-1", {"only": "this"}, merge=False
        )

        auth_service.update_user.assert_awaited_once_with(
            user_id="user-1", preferences={"only": "this"}
        )


class TestAuthenticatedPrincipal:
    """AUTH-07: typed trusted identity context."""

    def test_build_principal_from_user_account(self):
        user = MagicMock(
            id="user-1",
            email="user@example.com",
            tenant_id="tenant-a",
            roles=["admin", "user"],
            preferences={"permissions": ["chat:*", "admin:*"]},
            created_at=datetime.utcnow(),
        )
        principal = build_principal_from_user_account(user)

        assert isinstance(principal, AuthenticatedPrincipal)
        assert principal.user_id == "user-1"
        assert principal.tenant_id == "tenant-a"
        assert principal.roles == ["admin", "user"]
        assert principal.permissions == ["chat:*", "admin:*"]

    def test_has_role(self):
        principal = AuthenticatedPrincipal(
            user_id="user-1", roles=["admin", "user"]
        )
        assert principal.has_role("admin")
        assert principal.has_role("user")
        assert not principal.has_role("super_admin")

    def test_has_permission(self):
        principal = AuthenticatedPrincipal(
            user_id="user-1", permissions=["chat:*", "admin:*"]
        )
        assert principal.has_permission("chat:*")
        assert not principal.has_permission("training:*")

    def test_is_expired(self):
        principal = AuthenticatedPrincipal(
            user_id="user-1",
            expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
        assert principal.is_expired()

        principal2 = AuthenticatedPrincipal(
            user_id="user-1",
            expires_at=datetime.utcnow() + timedelta(minutes=1),
        )
        assert not principal2.is_expired()


class TestSessionAuthority:
    """AUTH-08: session authority cleanup."""

    @pytest.fixture
    def auth_service(self):
        service = AuthService()
        service._initialized = True
        return service

    @pytest.mark.asyncio
    async def test_list_sessions_reads_from_database(self, auth_service):
        auth_service._session_scope = AsyncMock()  # type: ignore[method-assign]
        mock_session = MagicMock()
        auth_service._session_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)  # type: ignore[attr-defined]
        auth_service._session_scope.return_value.__aexit__ = AsyncMock(return_value=False)  # type: ignore[attr-defined]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            MagicMock(
                session_token="token-1",
                user_id="user-1",
                access_token="access-1",
                refresh_token="refresh-1",
                expires_in=3600,
                created_at=datetime.utcnow(),
                last_accessed=datetime.utcnow(),
                ip_address="1.2.3.4",
                user_agent="test",
                device_fingerprint="fp",
                is_active=True,
                invalidated_at=None,
                invalidation_reason=None,
            )
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        sessions = await auth_service.list_sessions(user_id="user-1")
        assert len(sessions) == 1
        assert sessions[0]["session_token"] == "token-1"

    @pytest.mark.asyncio
    async def test_revoke_session_returns_false_when_missing(self, auth_service):
        auth_service._session_scope = AsyncMock()  # type: ignore[method-assign]
        mock_session = MagicMock()
        auth_service._session_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)  # type: ignore[attr-defined]
        auth_service._session_scope.return_value.__aexit__ = AsyncMock(return_value=False)  # type: ignore[attr-defined]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await auth_service.revoke_session("missing-token")
        assert result is False
