from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src/ai_karen_engine/services/auth/tenant_isolation.py"
SPEC = importlib.util.spec_from_file_location("tenant_isolation_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CrossTenantAccessError = MODULE.CrossTenantAccessError
TenantAccessLevel = MODULE.TenantAccessLevel
TenantContext = MODULE.TenantContext
TenantIsolationError = MODULE.TenantIsolationError
TenantValidator = MODULE.TenantValidator
VectorStoreTenantFilter = MODULE.VectorStoreTenantFilter


def _context(
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
    access_level=TenantAccessLevel.STRICT,
    allowed_tenants: set[str] | None = None,
):
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        access_level=access_level,
        allowed_tenants=allowed_tenants,
    )


def test_strict_tenant_context_denies_cross_tenant_access() -> None:
    validator = TenantValidator()
    context = _context()

    assert validator.check_tenant_access(context, "tenant-a") is True
    assert validator.check_tenant_access(context, "tenant-b") is False


def test_vector_query_rejects_cross_tenant_filter_instead_of_overwriting_silently() -> None:
    tenant_filter = VectorStoreTenantFilter()
    context = _context()

    with pytest.raises(CrossTenantAccessError):
        tenant_filter.validate_vector_query(
            context,
            {"tenant_id": "tenant-b", "topic": "distinctive-secret"},
            correlation_id="corr-tenant-boundary",
        )


def test_vector_query_injects_tenant_and_user_scope_when_filter_omits_them() -> None:
    tenant_filter = VectorStoreTenantFilter()
    context = _context()

    secured = tenant_filter.validate_vector_query(
        context,
        {"topic": "allowed"},
        correlation_id="corr-secure-filter",
    )

    assert secured["tenant_id"] == "tenant-a"
    assert secured["user_id"] == "user-a"
    assert secured["topic"] == "allowed"


def test_shared_access_requires_explicit_allowed_tenant() -> None:
    validator = TenantValidator()
    context = _context(
        access_level=TenantAccessLevel.SHARED,
        allowed_tenants={"tenant-a", "tenant-b"},
    )

    assert validator.check_tenant_access(context, "tenant-b") is True
    assert validator.check_tenant_access(context, "tenant-c") is False


def test_invalid_tenant_identifier_is_rejected_before_query_construction() -> None:
    tenant_filter = VectorStoreTenantFilter()
    context = _context(tenant_id="tenant-a; DROP TABLE auth_users")

    with pytest.raises(TenantIsolationError):
        tenant_filter.create_tenant_filter(context)


def test_strict_context_cannot_smuggle_allowed_tenants() -> None:
    validator = TenantValidator()
    context = _context(
        access_level=TenantAccessLevel.STRICT,
        allowed_tenants={"tenant-a", "tenant-b"},
    )

    assert validator.check_tenant_access(context, "tenant-b") is False
