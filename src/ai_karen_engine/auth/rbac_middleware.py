"""Role Based Access Control utilities for Kari AI."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Set, Union

from fastapi import Depends, HTTPException, Request, status

from .models import UserData
from .session import get_current_user as resolve_current_user
from ai_karen_engine.services.audit.audit_logging import (  # type: ignore
    get_audit_logger as resolve_audit_logger,
    AuditEvent,
    AuditEventType,
    AuditSeverity,
)
from ai_karen_engine.config import load_permissions_config


def get_audit_logger():
    """Wrapper used for dependency injection and testing."""

    return resolve_audit_logger()


logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """System permissions recognised by the RBAC layer."""

    # Legacy-friendly shorthand permissions
    READ = "read"
    EDIT = "edit"
    BROWSER = "browser"
    COMMAND = "command"
    MCP = "mcp"

    # Training and experimentation
    TRAINING_READ = "training:read"
    TRAINING_WRITE = "training:write"
    TRAINING_DELETE = "training:delete"
    TRAINING_EXECUTE = "training:execute"

    TRAINING_DATA_READ = "training_data:read"
    TRAINING_DATA_WRITE = "training_data:write"
    TRAINING_DATA_DELETE = "training_data:delete"

    # Model management
    MODEL_READ = "model:read"
    MODEL_WRITE = "model:write"
    MODEL_DELETE = "model:delete"
    MODEL_DEPLOY = "model:deploy"
    MODEL_LIST = "model:list"
    MODEL_INFO = "model:info"
    MODEL_DOWNLOAD = "model:download"
    MODEL_REMOVE = "model:remove"
    MODEL_ENSURE = "model:ensure"
    MODEL_GC = "model:gc"
    MODEL_REGISTRY_READ = "model:registry:read"
    MODEL_REGISTRY_WRITE = "model:registry:write"
    MODEL_HEALTH_CHECK = "model:health:check"
    MODEL_COMPATIBILITY_CHECK = "model:compatibility:check"
    MODEL_LICENSE_VIEW = "model:license:view"
    MODEL_LICENSE_ACCEPT = "model:license:accept"
    MODEL_LICENSE_MANAGE = "model:license:manage"
    MODEL_PIN = "model:pin"
    MODEL_UNPIN = "model:unpin"
    MODEL_QUOTA_MANAGE = "model:quota:manage"

    # Data operations
    DATA_READ = "data:read"
    DATA_WRITE = "data:write"
    DATA_DELETE = "data:delete"
    DATA_EXPORT = "data:export"

    # Scheduler
    SCHEDULER_READ = "scheduler:read"
    SCHEDULER_WRITE = "scheduler:write"
    SCHEDULER_EXECUTE = "scheduler:execute"

    # Administration
    ADMIN_READ = "admin:read"
    ADMIN_WRITE = "admin:write"
    ADMIN_SYSTEM = "admin:system"

    # Admin domain permissions
    ADMIN_USERS_READ = "admin.users:read"
    ADMIN_USERS_MANAGE = "admin.users:manage"
    ADMIN_TENANTS_READ = "admin.tenants:read"
    ADMIN_TENANTS_MANAGE = "admin.tenants:manage"
    ADMIN_PROVIDERS_READ = "admin.providers:read"
    ADMIN_PROVIDERS_MANAGE = "admin.providers:manage"
    ADMIN_PLUGINS_READ = "admin.plugins:read"
    ADMIN_PLUGINS_MANAGE = "admin.plugins:manage"
    ADMIN_AUDIT_READ = "admin.audit:read"
    ADMIN_RUNTIME_READ = "admin.runtime:read"
    ADMIN_RUNTIME_MANAGE = "admin.runtime:manage"
    ADMIN_HEALTH_READ = "admin.health:read"
    ADMIN_MEMORY_READ = "admin.memory:read"
    ADMIN_MEMORY_MANAGE = "admin.memory:manage"
    ADMIN_FEATURES_READ = "admin.features:read"
    ADMIN_FEATURES_MANAGE = "admin.features:manage"

    # Monitoring / security
    AUDIT_READ = "audit:read"
    SECURITY_READ = "security:read"
    SECURITY_WRITE = "security:write"
    SECURITY_EVIL_MODE = "security:evil_mode"

    # Routing / orchestration
    ROUTING_SELECT = "routing:select"
    ROUTING_PROFILE_VIEW = "routing:profile:view"
    ROUTING_PROFILE_MANAGE = "routing:profile:manage"
    ROUTING_HEALTH = "routing:health"
    ROUTING_AUDIT = "routing:audit"
    ROUTING_DRY_RUN = "routing:dry_run"


class Role(str, Enum):
    """System roles."""

    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    TRAINER = "trainer"
    ANALYST = "analyst"
    USER = "user"
    READONLY = "readonly"
    MODEL_MANAGER = "model_manager"
    DATA_STEWARD = "data_steward"
    ROUTING_ADMIN = "routing_admin"
    ROUTING_OPERATOR = "routing_operator"
    ROUTING_AUDITOR = "routing_auditor"


@dataclass(frozen=True)
class RolePermissions:
    role: Role
    permissions: Set[Permission]
    description: str
    inherits_from: Optional[Role] = None


def _all_permissions() -> Set[Permission]:
    return {permission for permission in Permission}


def _permissions_except(*excluded: Permission) -> Set[Permission]:
    excluded_set = set(excluded)
    return {permission for permission in Permission if permission not in excluded_set}


def _default_role_entries() -> Dict[str, Dict[str, Any]]:
    return {
        Role.SUPER_ADMIN.value: {
            "description": "Full system access",
            "permissions": ["*"],
        },
        Role.ADMIN.value: {
            "description": "Administrative access across the platform",
            "permissions": sorted(
                permission.value
                for permission in _permissions_except(Permission.SECURITY_EVIL_MODE)
            ),
        },
        Role.TRAINER.value: {
            "description": "Training and experimentation operator",
            "inherits_from": Role.USER.value,
            "permissions": [
                Permission.EDIT.value,
                Permission.COMMAND.value,
                Permission.TRAINING_WRITE.value,
                Permission.TRAINING_EXECUTE.value,
                Permission.TRAINING_DATA_READ.value,
                Permission.TRAINING_DATA_WRITE.value,
                Permission.MODEL_WRITE.value,
                Permission.MODEL_DEPLOY.value,
                Permission.MODEL_DOWNLOAD.value,
                Permission.MODEL_ENSURE.value,
                Permission.DATA_WRITE.value,
                Permission.SCHEDULER_READ.value,
                Permission.SCHEDULER_WRITE.value,
            ],
        },
        Role.ANALYST.value: {
            "description": "Read-focused analyst access",
            "inherits_from": Role.USER.value,
            "permissions": [
                Permission.AUDIT_READ.value,
                Permission.DATA_EXPORT.value,
                Permission.ROUTING_PROFILE_VIEW.value,
            ],
        },
        Role.USER.value: {
            "description": "Standard user access",
            "inherits_from": Role.READONLY.value,
            "permissions": [
                Permission.BROWSER.value,
                Permission.DATA_READ.value,
            ],
        },
        Role.READONLY.value: {
            "description": "Minimal read-only access",
            "permissions": [
                Permission.READ.value,
                Permission.TRAINING_READ.value,
                Permission.MODEL_READ.value,
                Permission.MODEL_LIST.value,
                Permission.MODEL_INFO.value,
            ],
        },
        Role.MODEL_MANAGER.value: {
            "description": "Model lifecycle management",
            "inherits_from": Role.USER.value,
            "permissions": [
                Permission.EDIT.value,
                Permission.COMMAND.value,
                Permission.MCP.value,
                Permission.MODEL_WRITE.value,
                Permission.MODEL_DELETE.value,
                Permission.MODEL_DEPLOY.value,
                Permission.MODEL_DOWNLOAD.value,
                Permission.MODEL_REMOVE.value,
                Permission.MODEL_ENSURE.value,
                Permission.MODEL_GC.value,
                Permission.MODEL_REGISTRY_READ.value,
                Permission.MODEL_REGISTRY_WRITE.value,
                Permission.MODEL_HEALTH_CHECK.value,
                Permission.MODEL_COMPATIBILITY_CHECK.value,
                Permission.MODEL_LICENSE_VIEW.value,
                Permission.MODEL_LICENSE_ACCEPT.value,
                Permission.MODEL_LICENSE_MANAGE.value,
                Permission.MODEL_PIN.value,
                Permission.MODEL_UNPIN.value,
                Permission.MODEL_QUOTA_MANAGE.value,
            ],
        },
        Role.DATA_STEWARD.value: {
            "description": "Data stewardship and governance",
            "inherits_from": Role.USER.value,
            "permissions": [
                Permission.EDIT.value,
                Permission.DATA_WRITE.value,
                Permission.DATA_DELETE.value,
                Permission.DATA_EXPORT.value,
                Permission.TRAINING_DATA_READ.value,
                Permission.TRAINING_DATA_WRITE.value,
                Permission.TRAINING_DATA_DELETE.value,
                Permission.SECURITY_READ.value,
            ],
        },
        Role.ROUTING_ADMIN.value: {
            "description": "Routing administration",
            "inherits_from": Role.ROUTING_OPERATOR.value,
            "permissions": [
                Permission.EDIT.value,
                Permission.ADMIN_READ.value,
                Permission.ROUTING_PROFILE_MANAGE.value,
                Permission.ROUTING_AUDIT.value,
            ],
        },
        Role.ROUTING_OPERATOR.value: {
            "description": "Routing operations",
            "inherits_from": Role.USER.value,
            "permissions": [
                Permission.COMMAND.value,
                Permission.ROUTING_SELECT.value,
                Permission.ROUTING_PROFILE_VIEW.value,
                Permission.ROUTING_HEALTH.value,
                Permission.ROUTING_DRY_RUN.value,
            ],
        },
        Role.ROUTING_AUDITOR.value: {
            "description": "Routing audit access",
            "inherits_from": Role.READONLY.value,
            "permissions": [
                Permission.BROWSER.value,
                Permission.AUDIT_READ.value,
                Permission.ROUTING_PROFILE_VIEW.value,
                Permission.ROUTING_HEALTH.value,
                Permission.ROUTING_AUDIT.value,
            ],
        },
    }


def _normalize_role_config(config: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(config.get("roles"), dict):
        return config["roles"]

    legacy = config.get("role_permissions")
    if not isinstance(legacy, dict):
        return {}

    normalized: Dict[str, Any] = {}
    for role_name, entry in legacy.items():
        if not isinstance(entry, dict):
            continue

        raw_permissions = entry.get("permissions", [])
        if raw_permissions == ["all"]:
            raw_permissions = ["*"]

        normalized[role_name] = {
            "description": entry.get("description", role_name),
            "permissions": raw_permissions,
            "inherits_from": entry.get("inherits_from"),
        }

    return normalized


@lru_cache()
def _load_permissions_config() -> Dict[str, Any]:
    """Load the canonical permission map shared with the frontend."""

    # First try environment override
    env_override = os.getenv("KARI_PERMISSIONS_CONFIG") or os.getenv(
        "PERMISSIONS_CONFIG_PATH"
    )
    if env_override and Path(env_override).exists():
        try:
            with open(env_override, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load permissions from {env_override}: {e}")

    # Use canonical loader
    config = load_permissions_config()
    if config:
        return config

    logger.warning("Missing permissions configuration; using built-in RBAC defaults.")
    return {}


_PERMISSION_ALIASES: Dict[str, Permission] = {
    "users:manage": Permission.ADMIN_WRITE,
    "system:configure": Permission.ADMIN_SYSTEM,
    "plugins:manage": Permission.ADMIN_WRITE,
    "chat:use": Permission.BROWSER,
    "data:read_own": Permission.DATA_READ,
    "profile:manage_own": Permission.EDIT,
}


def _resolve_permission_names(raw_permissions: Iterable[str]) -> Set[Permission]:
    resolved: Set[Permission] = set()
    for value in raw_permissions:
        try:
            resolved.add(Permission(value))
        except ValueError:
            alias = _PERMISSION_ALIASES.get(value)
            if alias is not None:
                resolved.add(alias)
                continue
            logger.warning("Unknown permission '%s' in permissions.json", value)
    return resolved


def _build_role_permissions() -> Dict[Role, RolePermissions]:
    config = _load_permissions_config()
    role_config = _normalize_role_config(config)
    default_role_config = _default_role_entries()
    role_permissions: Dict[Role, RolePermissions] = {}

    for role in Role:
        entry = role_config.get(role.value) or {}
        default_entry = default_role_config.get(role.value, {})

        inherits_from = entry.get("inherits_from", default_entry.get("inherits_from"))
        inherited_role: Optional[Role] = None
        if inherits_from:
            try:
                inherited_role = Role(inherits_from)
            except ValueError:
                logger.warning(
                    "Invalid role inheritance '%s' configured for role '%s'",
                    inherits_from,
                    role.value,
                )

        raw_permissions = entry.get("permissions", default_entry.get("permissions", []))
        if isinstance(raw_permissions, list) and raw_permissions in (["*"], ["all"]):
            permissions = _all_permissions()
        else:
            permissions = _resolve_permission_names(raw_permissions)
            if raw_permissions and not permissions and default_entry.get("permissions"):
                logger.warning(
                    "No recognized permissions configured for role '%s'; using built-in defaults",
                    role.value,
                )
                permissions = _resolve_permission_names(default_entry["permissions"])

        role_permissions[role] = RolePermissions(
            role=role,
            permissions=permissions,
            description=str(
                entry.get("description", default_entry.get("description", role.value))
            ),
            inherits_from=inherited_role,
        )

    return role_permissions


ROLE_PERMISSIONS: Dict[Role, RolePermissions] = _build_role_permissions()


class RBACManager:
    """Provide permission evaluation utilities."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self._role_permissions = ROLE_PERMISSIONS
        self._audit_logger = None

    # ------------------------------------------------------------------
    def _collect_permissions(self, role: Role, aggregate: Set[Permission]) -> None:
        entry = self._role_permissions.get(role)
        if not entry:
            return
        aggregate.update(entry.permissions)
        if entry.inherits_from:
            self._collect_permissions(entry.inherits_from, aggregate)

    def get_user_permissions(self, user: UserData) -> Set[Permission]:
        permissions: Set[Permission] = set()
        for role_name in user.get("roles", []):
            try:
                role = Role(role_name.lower())
            except ValueError:
                logger.debug(
                    "Unknown role '%s' for user %s", role_name, user.get("user_id")
                )
                continue
            self._collect_permissions(role, permissions)
        return permissions

    def has_permission(
        self,
        user: Union[UserData, Dict[str, object]],
        permission: Union[Permission, str],
    ) -> bool:
        user_data = UserData.ensure(user)
        target = _ensure_permission(permission)
        user_permissions = self.get_user_permissions(user_data)
        if isinstance(target, Permission):
            return target in user_permissions
        return any(str(p) == str(target) for p in user_permissions)

    def has_any_permission(
        self,
        user: Union[UserData, Dict[str, object]],
        permissions: Iterable[Union[Permission, str]],
    ) -> bool:
        return any(self.has_permission(user, permission) for permission in permissions)

    def has_all_permissions(
        self,
        user: Union[UserData, Dict[str, object]],
        permissions: Iterable[Union[Permission, str]],
    ) -> bool:
        return all(self.has_permission(user, permission) for permission in permissions)

    def has_role(
        self, user: Union[UserData, Dict[str, object]], role: Union[Role, str]
    ) -> bool:
        user_data = UserData.ensure(user)
        target = role.value if isinstance(role, Role) else str(role).lower()
        user_roles = {r.lower() for r in user_data.get("roles", [])}
        return target in user_roles

    def has_super_admin_role(self, user: Union[UserData, Dict[str, object]]) -> bool:
        return self.has_role(user, Role.SUPER_ADMIN)

    def has_admin_role(self, user: Union[UserData, Dict[str, object]]) -> bool:
        return self.has_role(user, Role.ADMIN) or self.has_super_admin_role(user)

    def audit_access_attempt(
        self,
        user_data: Union[UserData, Dict[str, Any]],
        permission: Union[Permission, str],
        resource: str,
        granted: bool,
        request: Optional[Request] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an audit event describing an access control decision."""

        user = UserData.ensure(user_data)
        metadata: Dict[str, Any] = {
            "permission": str(_ensure_permission(permission)),
            "resource": resource,
            "granted": granted,
            "user_roles": user.get("roles", []),
            "tenant_id": user.get("tenant_id"),
        }
        if additional_context:
            metadata.update(additional_context)

        ip_address = "unknown"
        user_agent = ""
        if request is not None and request.client is not None:
            ip_address = request.client.host or ip_address
            user_agent = request.headers.get("user-agent", "")

        payload = {
            "event_type": "access_granted" if granted else "access_denied",
            "severity": "info" if granted else "warning",
            "message": f"Access {'granted' if granted else 'denied'} to {metadata['permission']} for resource {resource}",
            "user_id": user.get("user_id"),
            "tenant_id": user.get("tenant_id"),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "metadata": metadata,
        }

        try:
            audit_logger = self._get_audit_logger()
            if audit_logger is None:
                logger.info(payload["message"])
                return

            try:
                audit_logger.log_audit_event(payload)
            except TypeError:
                event = AuditEvent(
                    event_type=AuditEventType.LOGIN_SUCCESS
                    if granted
                    else AuditEventType.LOGIN_FAILURE,
                    severity=AuditSeverity.INFO if granted else AuditSeverity.WARNING,
                    message=payload["message"],
                    user_id=payload["user_id"],
                    tenant_id=payload["tenant_id"],
                    ip_address=payload["ip_address"],
                    user_agent=payload["user_agent"],
                    metadata=metadata,
                )
                audit_logger.log_audit_event(event)
        except Exception as exc:  # pragma: no cover - logging safety
            logger.error("Failed to record RBAC audit event: %s", exc)

    def _get_audit_logger(self):
        if self._audit_logger is None:
            try:
                self._audit_logger = get_audit_logger()
            except Exception:  # pragma: no cover - audit service optional
                self._audit_logger = None
        return self._audit_logger


@lru_cache
def get_rbac_manager() -> RBACManager:
    return RBACManager()


def _ensure_permission(permission: Union[Permission, str]) -> Union[Permission, str]:
    if isinstance(permission, Permission):
        return permission
    try:
        return Permission(permission)
    except ValueError:
        return permission


def check_training_access(
    user: Union[UserData, Dict[str, object]], level: str = "read"
) -> bool:
    level = level.lower()
    requirements = {
        "read": {Permission.TRAINING_READ, Permission.TRAINING_DATA_READ},
        "write": {
            Permission.TRAINING_WRITE,
            Permission.TRAINING_EXECUTE,
            Permission.TRAINING_DATA_WRITE,
        },
        "delete": {Permission.TRAINING_DELETE, Permission.TRAINING_DATA_DELETE},
        "execute": {Permission.TRAINING_EXECUTE},
    }
    required = requirements.get(level, {Permission.TRAINING_READ})
    return get_rbac_manager().has_any_permission(user, required)


def check_model_access(
    user: Union[UserData, Dict[str, object]], action: str = "read"
) -> bool:
    action = action.lower()
    requirements = {
        "read": {
            Permission.MODEL_READ,
            Permission.MODEL_INFO,
            Permission.MODEL_LIST,
            Permission.MODEL_HEALTH_CHECK,
        },
        "write": {
            Permission.MODEL_WRITE,
            Permission.MODEL_DOWNLOAD,
            Permission.MODEL_ENSURE,
            Permission.MODEL_PIN,
            Permission.MODEL_UNPIN,
        },
        "delete": {
            Permission.MODEL_DELETE,
            Permission.MODEL_REMOVE,
            Permission.MODEL_GC,
        },
        "deploy": {Permission.MODEL_DEPLOY},
        "registry": {Permission.MODEL_REGISTRY_READ, Permission.MODEL_REGISTRY_WRITE},
    }
    required = requirements.get(action, {Permission.MODEL_READ})
    return get_rbac_manager().has_any_permission(user, required)


def check_data_access(
    user: Union[UserData, Dict[str, object]], level: str = "read"
) -> bool:
    level = level.lower()
    requirements = {
        "read": {Permission.DATA_READ, Permission.TRAINING_DATA_READ},
        "write": {Permission.DATA_WRITE, Permission.TRAINING_DATA_WRITE},
        "delete": {Permission.DATA_DELETE, Permission.TRAINING_DATA_DELETE},
        "export": {Permission.DATA_EXPORT},
    }
    required = requirements.get(level, {Permission.DATA_READ})
    return get_rbac_manager().has_any_permission(user, required)


def check_scheduler_access(
    user: Union[UserData, Dict[str, object]], level: str = "read"
) -> bool:
    level = level.lower()
    requirements = {
        "read": {Permission.SCHEDULER_READ},
        "write": {Permission.SCHEDULER_WRITE},
        "execute": {Permission.SCHEDULER_EXECUTE},
    }
    required = requirements.get(level, {Permission.SCHEDULER_READ})
    return get_rbac_manager().has_any_permission(user, required)


def check_admin_access(
    user: Union[UserData, Dict[str, object]], level: str = "read"
) -> bool:
    level = level.lower()
    requirements = {
        "read": {Permission.ADMIN_READ},
        "write": {Permission.ADMIN_WRITE},
        "system": {Permission.ADMIN_SYSTEM},
    }
    required = requirements.get(level, {Permission.ADMIN_READ})
    return get_rbac_manager().has_any_permission(user, required)


def require_permission(permission: Union[Permission, str]) -> Callable:
    target = _ensure_permission(permission)

    async def dependency(
        current_user: UserData = Depends(resolve_current_user),
    ) -> UserData:
        if not get_rbac_manager().has_permission(current_user, target):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied"
            )
        return current_user

    return dependency


def require_scopes(*permissions: Union[Permission, str]) -> Callable:
    targets = [_ensure_permission(permission) for permission in permissions]

    async def dependency(
        current_user: UserData = Depends(resolve_current_user),
    ) -> UserData:
        if not get_rbac_manager().has_all_permissions(current_user, targets):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return current_user

    return dependency


async def check_scope(request: Request, permission: Union[Permission, str]) -> bool:
    current_user = await resolve_current_user(request)
    return get_rbac_manager().has_permission(
        current_user, _ensure_permission(permission)
    )


get_current_user = resolve_current_user


__all__ = [
    "Permission",
    "Role",
    "RBACManager",
    "get_rbac_manager",
    "require_permission",
    "require_scopes",
    "check_training_access",
    "check_model_access",
    "check_data_access",
    "check_scheduler_access",
    "check_admin_access",
    "check_scope",
    "get_current_user",
]
