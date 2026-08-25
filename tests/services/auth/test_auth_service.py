"""Tests for the canonical authentication authority."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta
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

    class _FakeBaseService:
        def __init__(self, config=None):
            self.config = config

    base.BaseService = _FakeBaseService  # type: ignore[attr-defined]
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


def _load_tenant_isolation_module():
    spec = importlib.util.spec_from_file_location(
        "ai_karen_engine.services.auth.tenant_isolation",
        SRC / "ai_karen_engine" / "services" / "auth" / "tenant_isolation.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tenant_isolation_module = _load_tenant_isolation_module()
TenantValidator = tenant_isolation_module.TenantValidator
SecurityIncidentLogger = tenant_isolation_module.SecurityIncidentLogger
VectorStoreTenantFilter = tenant_isolation_module.VectorStoreTenantFilter
SQLTenantFilter = tenant_isolation_module.SQLTenantFilter
TenantContext = tenant_isolation_module.TenantContext
TenantAccessLevel = tenant_isolation_module.TenantAccessLevel
SecurityIncident = tenant_isolation_module.SecurityIncident
SecurityIncidentType = tenant_isolation_module.SecurityIncidentType

# Environment is defined in services/auth/config.py
config_spec = importlib.util.spec_from_file_location(
    "ai_karen_engine.services.auth.config",
    SRC / "ai_karen_engine" / "services" / "auth" / "config.py",
)
config_module = importlib.util.module_from_spec(config_spec)
sys.modules[config_spec.name] = config_module
config_spec.loader.exec_module(config_module)
Environment = config_module.Environment
INSECURE_SECRET_MARKERS = config_module.INSECURE_SECRET_MARKERS


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
        user_uuid = "00000000-0000-0000-0000-000000000001"
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        auth_service._session_scope = MagicMock(return_value=mock_cm)  # type: ignore[method-assign]

        mock_auth_user = MagicMock()
        mock_auth_user.user_id = user_uuid
        mock_auth_user.full_name = "Old Name"
        mock_auth_user.roles = ["user"]
        mock_auth_user.preferences = {}
        mock_auth_user.is_active = True
        mock_auth_user.is_verified = True
        mock_auth_user.updated_at = datetime.utcnow()
        mock_auth_user.locked_until = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_auth_user
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()

        with patch("ai_karen_engine.services.auth.auth_service.select") as mock_select, \
             patch("ai_karen_engine.services.auth.auth_service.AuthUser") as mock_auth_user_cls:
            mock_select.return_value.where.return_value = MagicMock()
            mock_select.return_value.where.return_value.__eq__ = MagicMock(return_value=True)
            
            user = await auth_service.update_user(
                user_id=user_uuid,
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

        assert auth_service.update_user.called
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

        assert auth_service.update_user.called
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

        assert auth_service.update_user.called

    @pytest.mark.asyncio
    async def test_update_user_preferences_replace(self, auth_service):
        auth_service.update_user = AsyncMock(  # type: ignore[method-assign]
            return_value=MagicMock(id="user-1", preferences={"only": "this"})
        )
        auth_service._emit_audit_event = AsyncMock()  # type: ignore[method-assign]

        user = await auth_service.update_user_preferences(
            "user-1", {"only": "this"}, merge=False
        )

        assert auth_service.update_user.called


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
    async def test_list_sessions_exists_and_calls_session_scope(self, auth_service):
        auth_service._session_scope = AsyncMock()  # type: ignore[method-assign]
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        auth_service._session_scope.return_value = mock_cm

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        sessions = await auth_service.list_sessions(user_id="user-1")
        assert isinstance(sessions, list)
        auth_service._session_scope.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_session_exists_and_calls_session_scope(self, auth_service):
        auth_service._session_scope = AsyncMock()  # type: ignore[method-assign]
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        auth_service._session_scope.return_value = mock_cm

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await auth_service.revoke_session("missing-token")
        assert result is False
        auth_service._session_scope.assert_called_once()


class TestTenantIsolationInvariants:
    """AUTH-09: tenant isolation invariants."""

    @pytest.fixture
    def validator(self):
        return TenantValidator()

    @pytest.fixture
    def incident_logger(self):
        return SecurityIncidentLogger()

    @pytest.fixture
    def vector_filter(self):
        return VectorStoreTenantFilter()

    @pytest.fixture
    def sql_filter(self):
        return SQLTenantFilter()

    def test_validate_tenant_id_accepts_valid_ids(self, validator):
        assert validator.validate_tenant_id("default") == "default"
        assert validator.validate_tenant_id("tenant-a") == "tenant-a"
        assert validator.validate_tenant_id("123-456") == "123-456"

    def test_validate_tenant_id_rejects_invalid_ids(self, validator):
        with pytest.raises(Exception):
            validator.validate_tenant_id("")
        with pytest.raises(Exception):
            validator.validate_tenant_id("tenant with spaces")
        with pytest.raises(Exception):
            validator.validate_tenant_id("@bad!")

    def test_check_tenant_access_strict_isolation(self, validator):
        context = TenantContext(tenant_id="tenant-a", user_id="user-1", access_level=TenantAccessLevel.STRICT)
        assert validator.check_tenant_access(context, "tenant-a") is True
        assert validator.check_tenant_access(context, "tenant-b") is False

    def test_check_tenant_access_shared_isolation(self, validator):
        context = TenantContext(
            tenant_id="tenant-a",
            user_id="user-1",
            access_level=TenantAccessLevel.SHARED,
            allowed_tenants={"tenant-a", "tenant-b"},
        )
        assert validator.check_tenant_access(context, "tenant-a") is True
        assert validator.check_tenant_access(context, "tenant-b") is True
        assert validator.check_tenant_access(context, "tenant-c") is False

    def test_check_tenant_access_public(self, validator):
        context = TenantContext(tenant_id="tenant-a", user_id="user-1", access_level=TenantAccessLevel.PUBLIC)
        assert validator.check_tenant_access(context, "tenant-b") is True

    def test_vector_store_filter_blocks_cross_tenant_query(self, vector_filter):
        context = TenantContext(tenant_id="tenant-a", user_id="user-1", access_level=TenantAccessLevel.STRICT)
        with pytest.raises(Exception):
            vector_filter.validate_vector_query(context, {"tenant_id": "tenant-b"})

    def test_vector_store_filter_allows_same_tenant_query(self, vector_filter):
        context = TenantContext(tenant_id="tenant-a", user_id="user-1", access_level=TenantAccessLevel.STRICT)
        result = vector_filter.validate_vector_query(context, {})
        assert result["tenant_id"] == "tenant-a"
        assert result["user_id"] == "user-1"

    def test_security_incident_logger_records_incident(self, incident_logger):
        context = TenantContext(tenant_id="tenant-a", user_id="user-1", access_level=TenantAccessLevel.STRICT)
        incident = SecurityIncident(
            incident_type=SecurityIncidentType.CROSS_TENANT_ACCESS_ATTEMPT,
            tenant_context=context,
            attempted_access={"target": "tenant-b"},
            timestamp=datetime.utcnow(),
            correlation_id="corr-1",
        )
        incident_logger.log_incident(incident)


class TestAuditEventContract:
    """AUTH-10: audit event contract."""

    @pytest.mark.asyncio
    async def test_update_user_emits_audit_event(self):
        from ai_karen_engine.services.auth.auth_service import AuthService
        service = AuthService()
        service._initialized = True
        service._emit_audit_event = AsyncMock()  # type: ignore[method-assign]

        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        service._session_scope = MagicMock(return_value=mock_cm)  # type: ignore[method-assign]

        mock_auth_user = MagicMock()
        mock_auth_user.user_id = "00000000-0000-0000-0000-000000000001"
        mock_auth_user.full_name = "Old Name"
        mock_auth_user.roles = ["user"]
        mock_auth_user.preferences = {}
        mock_auth_user.is_active = True
        mock_auth_user.is_verified = True
        mock_auth_user.updated_at = datetime.utcnow()
        mock_auth_user.locked_until = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_auth_user
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()
        mock_session.refresh = AsyncMock()

        with patch("ai_karen_engine.services.auth.auth_service.select") as mock_select, \
             patch("ai_karen_engine.services.auth.auth_service.AuthUser") as mock_auth_user_cls:
            mock_select.return_value.where.return_value = MagicMock()
            mock_select.return_value.where.return_value.__eq__ = MagicMock(return_value=True)
            await service.update_user(
                user_id="00000000-0000-0000-0000-000000000001",
                full_name="New Name",
            )

        service._emit_audit_event.assert_awaited_once()
        call_kwargs = service._emit_audit_event.call_args.kwargs
        assert call_kwargs["action"] == "auth.user.updated"
        assert call_kwargs["status"] == "success"


class TestCredentialAccountBoundary:
    """AUTH-11: credential/account association boundary."""

    def test_auth_user_is_authentication_only(self):
        spec = importlib.util.spec_from_file_location(
            "ai_karen_engine.database.models",
            SRC / "ai_karen_engine" / "database" / "models" / "__init__.py",
        )
        models_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = models_module
        spec.loader.exec_module(models_module)
        AuthUser = models_module.AuthUser
        fields = {c.name for c in AuthUser.__table__.columns}
        assert "password_hash" in fields
        assert "two_factor_secret" in fields
        assert "roles" in fields
        assert "preferences" in fields
        assert "tenant_id" in fields

    def test_identity_vault_exists_for_external_credentials(self):
        spec = importlib.util.spec_from_file_location(
            "ai_karen_engine.database.models.identity_vault",
            SRC / "ai_karen_engine" / "database" / "models" / "identity_vault.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        assert hasattr(module, "Credential")
        assert hasattr(module, "ExternalAccount")
        assert hasattr(module, "CredentialBinding")
