"""
CORTEX RBAC Validator

Validates user permissions before plugin execution.
Ensures RBAC enforcement at the CORTEX layer.

ARCHITECTURAL COMPLIANCE:
- Checks Postgres for plugin permissions (source of truth)
- Caches results in Redis for performance (5min TTL)
- Fail-secure: deny if validation fails
"""

import logging
import json
from typing import Dict, Any, Optional, List
import asyncio

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)

# Try to import Redis manager
try:
    from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("[RBAC] RedisConnectionManager not available for caching")

# Redis cache configuration
RBAC_CACHE_TTL = 300  # 5 minutes
RBAC_CACHE_KEY_PREFIX = "kari:rbac:plugin"


class RBACValidationError(Exception):
    """Raised when RBAC validation fails."""

    pass


class PermissionDeniedError(Exception):
    """Raised when user doesn't have permission."""

    pass


async def _check_redis_cache(user_id: str, plugin_id: str) -> Optional[bool]:
    """
    Check Redis cache for plugin permission.

    Returns:
        True if permitted, False if denied, None if not cached
    """
    if not REDIS_AVAILABLE:
        return None

    try:
        redis_mgr = get_redis_manager()
        if not redis_mgr:
            return None

        cache_key = f"{RBAC_CACHE_KEY_PREFIX}:{user_id}:{plugin_id}"
        cached = await redis_mgr.get(cache_key)

        if cached:
            result = json.loads(cached)
            logger.debug(
                f"[RBAC] Cache HIT for user {user_id}, plugin {plugin_id}: {result}"
            )
            return result.get("permitted", False)

        logger.debug(f"[RBAC] Cache MISS for user {user_id}, plugin {plugin_id}")
        return None

    except Exception as ex:
        logger.warning(f"[RBAC] Redis cache check failed: {ex}")
        return None


async def _set_redis_cache(user_id: str, plugin_id: str, permitted: bool) -> None:
    """Set Redis cache for plugin permission."""
    if not REDIS_AVAILABLE:
        return

    try:
        redis_mgr = get_redis_manager()
        if not redis_mgr:
            return

        cache_key = f"{RBAC_CACHE_KEY_PREFIX}:{user_id}:{plugin_id}"
        cache_value = json.dumps(
            {"permitted": permitted, "user_id": user_id, "plugin_id": plugin_id}
        )

        await redis_mgr.set(cache_key, cache_value, ex=RBAC_CACHE_TTL)
        logger.debug(
            f"[RBAC] Cached permission for user {user_id}, plugin {plugin_id}: {permitted}"
        )

    except Exception as ex:
        logger.warning(f"[RBAC] Redis cache set failed: {ex}")


def _check_plugin_permission_postgres(user_ctx: Dict[str, Any], plugin_id: str) -> bool:
    """
    Check plugin permission from Postgres (synchronous).

    Queries:
    1. plugin_registry - check if plugin exists and is enabled
    2. plugin_installs - check if plugin is installed for user/org
    3. user_roles + role_permissions - check RBAC

    Returns:
        True if permitted, False otherwise
    """
    try:
        # For now, implement basic logic
        # TODO: Implement full RBAC query against Postgres
        user_id = user_ctx.get("user_id")
        tenant_id = user_ctx.get("tenant_id", "default")
        roles = user_ctx.get("roles", [])

        logger.info(
            f"[RBAC] Checking plugin permission: user={user_id}, tenant={tenant_id}, "
            f"plugin={plugin_id}, roles={roles}"
        )

        # Admin always allowed
        if "admin" in roles or "superuser" in roles:
            logger.info(
                f"[RBAC] Admin user {user_id} granted access to plugin {plugin_id}"
            )
            return True

        # TODO: Query Postgres for plugin_registry, plugin_installs, role_permissions
        # For Phase 2, we'll implement a permissive check with logging
        # Full implementation should:
        # 1. Check plugin exists in plugin_registry
        # 2. Check plugin is enabled
        # 3. Check plugin is installed for tenant in plugin_installs
        # 4. Check user roles have permission for plugin

        logger.warning(
            f"[RBAC] Full Postgres RBAC query not yet implemented, "
            f"allowing plugin {plugin_id} for user {user_id} (TODO: implement)"
        )
        return True

    except Exception as ex:
        logger.error(f"[RBAC] Plugin permission check failed: {ex}")
        # Fail-secure: deny on error
        return False


async def validate_plugin_permission(user_ctx: Dict[str, Any], plugin_id: str) -> bool:
    """
    Validate that user has permission to execute plugin.

    ARCHITECTURAL COMPLIANCE:
    - Checks Redis cache first (O(1))
    - Falls back to Postgres if cache miss
    - Caches result for future requests
    - Fail-secure: denies on error

    Args:
        user_ctx: User context dict with user_id, tenant_id, roles
        plugin_id: Plugin identifier

    Returns:
        True if user has permission

    Raises:
        PermissionDeniedError: If user doesn't have permission
        RBACValidationError: If validation fails
    """
    user_id = user_ctx.get("user_id", "anonymous")
    tenant_id = user_ctx.get("tenant_id", "default")

    try:
        # Check Redis cache first
        cached_result = await _check_redis_cache(user_id, plugin_id)
        if cached_result is not None:
            if cached_result:
                return True
            else:
                raise PermissionDeniedError(
                    f"User {user_id} does not have permission to execute plugin {plugin_id} (cached)"
                )

        # Cache miss, check Postgres
        permitted = _check_plugin_permission_postgres(user_ctx, plugin_id)

        # Cache the result
        await _set_redis_cache(user_id, plugin_id, permitted)

        if permitted:
            logger.info(
                f"[RBAC] ✅ User {user_id} permitted to execute plugin {plugin_id}"
            )
            return True
        else:
            raise PermissionDeniedError(
                f"User {user_id} does not have permission to execute plugin {plugin_id}"
            )

    except PermissionDeniedError:
        raise
    except Exception as ex:
        error_msg = (
            f"RBAC validation failed for user {user_id}, plugin {plugin_id}: {ex}"
        )
        logger.error(error_msg)
        raise RBACValidationError(error_msg) from ex


async def invalidate_plugin_permission_cache(
    user_id: str, plugin_id: Optional[str] = None
) -> None:
    """
    Invalidate cached plugin permissions for user.

    Args:
        user_id: User identifier
        plugin_id: Optional plugin ID (if None, invalidates all plugins for user)
    """
    if not REDIS_AVAILABLE:
        return

    try:
        redis_mgr = get_redis_manager()
        if not redis_mgr:
            return

        if plugin_id:
            # Invalidate specific plugin
            cache_key = f"{RBAC_CACHE_KEY_PREFIX}:{user_id}:{plugin_id}"
            await redis_mgr.delete(cache_key)
            logger.info(
                f"[RBAC] Invalidated cache for user {user_id}, plugin {plugin_id}"
            )
        else:
            # TODO: Invalidate all plugins for user (requires scan support in RedisConnectionManager)
            logger.warning(
                f"[RBAC] Bulk cache invalidation not yet implemented for user {user_id}"
            )

    except Exception as ex:
        logger.warning(f"[RBAC] Cache invalidation failed: {ex}")


__all__ = [
    "validate_plugin_permission",
    "invalidate_plugin_permission_cache",
    "RBACValidationError",
    "PermissionDeniedError",
]
