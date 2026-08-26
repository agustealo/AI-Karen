"""Canonical auth services package boundary.

Auth submodules are loaded lazily so importing the canonical ``AuthService``
does not initialize authorization middleware, FastAPI integration, data
protection, tenant tooling, or user-management stacks. Public exports remain
stable for compatibility while ownership stays with each concrete submodule.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "AuthService": (".auth_service", "AuthService"),
    "Session": (".auth_service", "Session"),
    "UserAccount": (".auth_service", "UserAccount"),
    "UserRole": (".auth_service", "UserRole"),
    "UserStatus": (".auth_service", "UserStatus"),
    "AuthorizationConfig": (".authorization_service", "AuthorizationConfig"),
    "AuthorizationService": (".authorization_service", "AuthorizationService"),
    "Policy": (".authorization_service", "Policy"),
    "PolicyEnforcementResult": (".authorization_service", "PolicyEnforcementResult"),
    "PolicyType": (".authorization_service", "PolicyType"),
    "INSECURE_SECRET_MARKERS": (".config", "INSECURE_SECRET_MARKERS"),
    "AuthConfig": (".config", "AuthConfig"),
    "Environment": (".config", "Environment"),
    "load_auth_config": (".config", "load_auth_config"),
    "DataProtectionConfig": (".data_protection_service", "DataProtectionConfig"),
    "DataProtectionPolicy": (".data_protection_service", "DataProtectionPolicy"),
    "DataProtectionResult": (".data_protection_service", "DataProtectionResult"),
    "DataProtectionService": (".data_protection_service", "DataProtectionService"),
    "DataSensitivity": (".data_protection_service", "DataSensitivity"),
    "EncryptionAlgorithm": (".data_protection_service", "EncryptionAlgorithm"),
    "EncryptionKey": (".data_protection_service", "EncryptionKey"),
    "RetentionPolicy": (".data_protection_service", "RetentionPolicy"),
    "CrossTenantAccessError": (".tenant_isolation", "CrossTenantAccessError"),
    "SecurityIncident": (".tenant_isolation", "SecurityIncident"),
    "SecurityIncidentLogger": (".tenant_isolation", "SecurityIncidentLogger"),
    "SecurityIncidentType": (".tenant_isolation", "SecurityIncidentType"),
    "TenantAccessLevel": (".tenant_isolation", "TenantAccessLevel"),
    "TenantContext": (".tenant_isolation", "TenantContext"),
    "TenantIsolationError": (".tenant_isolation", "TenantIsolationError"),
    "TenantIsolationService": (".tenant_isolation", "TenantIsolationService"),
    "TenantValidator": (".tenant_isolation", "TenantValidator"),
    "VectorStoreTenantFilter": (".tenant_isolation", "VectorStoreTenantFilter"),
    "create_tenant_context": (".tenant_isolation", "create_tenant_context"),
    "get_tenant_isolation_service": (".tenant_isolation", "get_tenant_isolation_service"),
    "validate_tenant_access": (".tenant_isolation", "validate_tenant_access"),
    "TenantNotFoundError": (".user_service", "TenantNotFoundError"),
    "UserAlreadyExistsError": (".user_service", "UserAlreadyExistsError"),
    "UserNotFoundError": (".user_service", "UserNotFoundError"),
    "UserService": (".user_service", "UserService"),
    "UserServiceError": (".user_service", "UserServiceError"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
