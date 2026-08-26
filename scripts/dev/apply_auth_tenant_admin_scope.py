from __future__ import annotations

from pathlib import Path

ROUTE = Path("src/ai_karen_engine/api_routes/auth/auth.py")
SERVICE = Path("src/ai_karen_engine/services/auth/auth_service.py")


def main() -> None:
    route = ROUTE.read_text(encoding="utf-8")

    helper_marker = '''def _resolve_current_user_id(user: Any) -> str:\n    """Resolve current user ID from either a dict payload or a user-like object."""\n    payload = _ensure_authenticated_user_payload(user)\n    return payload["user_id"]\n'''
    helper = helper_marker + '''\n\ndef _require_tenant_scope(user: Any) -> str:\n    """Return an explicit tenant scope for tenant-admin operations."""\n    tenant_id = str(_user_value(user, "tenant_id", "") or "").strip()\n    if not tenant_id or tenant_id == "default":\n        raise HTTPException(\n            status_code=status.HTTP_403_FORBIDDEN,\n            detail="Explicit tenant scope is required for this operation",\n        )\n    return tenant_id\n'''
    if helper_marker not in route:
        raise RuntimeError("tenant helper marker not found")
    route = route.replace(helper_marker, helper, 1)

    create_marker = '''    user, error = await auth_svc.create_user(\n        email=request.email,\n        password=request.password,\n        full_name=request.full_name,\n        roles=request.roles,\n    )\n'''
    create_replacement = '''    tenant_id = _require_tenant_scope(current_user)\n    user, error = await auth_svc.create_user(\n        email=request.email,\n        password=request.password,\n        full_name=request.full_name,\n        tenant_id=tenant_id,\n        roles=request.roles,\n    )\n'''
    if create_marker not in route:
        raise RuntimeError("create-user marker not found")
    route = route.replace(create_marker, create_replacement, 1)

    stats_marker = '''    stats = await auth_svc.get_auth_stats()\n    return stats\n'''
    stats_replacement = '''    tenant_id = None\n    if not _has_role(current_user, "super_admin"):\n        tenant_id = _require_tenant_scope(current_user)\n    stats = await auth_svc.get_auth_stats(tenant_id=tenant_id)\n    return stats\n'''
    if stats_marker not in route:
        raise RuntimeError("stats marker not found")
    route = route.replace(stats_marker, stats_replacement, 1)
    ROUTE.write_text(route, encoding="utf-8")

    service = SERVICE.read_text(encoding="utf-8")
    start = service.index("    async def get_auth_stats(")
    end = service.index("    async def is_first_run(", start)
    replacement = '''    async def get_auth_stats(\n        self, tenant_id: Optional[str] = None\n    ) -> Dict[str, Any]:\n        """Get authentication statistics, optionally scoped to one tenant."""\n        try:\n            tenant_uuid: Optional[uuid.UUID] = None\n            if tenant_id is not None:\n                try:\n                    tenant_uuid = uuid.UUID(str(tenant_id))\n                except ValueError:\n                    return {\n                        "total_users": 0,\n                        "active_users": 0,\n                        "total_sessions": 0,\n                        "active_sessions": 0,\n                        "service_status": "error",\n                        "error": "Invalid tenant scope",\n                    }\n\n            async with self._session_scope() as session:\n                user_query = select(func.count()).select_from(AuthUser)\n                active_user_query = (\n                    select(func.count())\n                    .select_from(AuthUser)\n                    .where(AuthUser.is_active)\n                )\n                session_query = select(func.count()).select_from(AuthSession)\n                active_session_query = (\n                    select(func.count())\n                    .select_from(AuthSession)\n                    .join(AuthUser, AuthUser.user_id == AuthSession.user_id)\n                    .where(AuthSession.is_active)\n                )\n\n                if tenant_uuid is not None:\n                    user_query = user_query.where(AuthUser.tenant_id == tenant_uuid)\n                    active_user_query = active_user_query.where(\n                        AuthUser.tenant_id == tenant_uuid\n                    )\n                    session_query = (\n                        session_query\n                        .join(AuthUser, AuthUser.user_id == AuthSession.user_id)\n                        .where(AuthUser.tenant_id == tenant_uuid)\n                    )\n                    active_session_query = active_session_query.where(\n                        AuthUser.tenant_id == tenant_uuid\n                    )\n\n                total_users = (await session.execute(user_query)).scalar() or 0\n                active_users = (await session.execute(active_user_query)).scalar() or 0\n                total_sessions = (await session.execute(session_query)).scalar() or 0\n                active_sessions = (\n                    await session.execute(active_session_query)\n                ).scalar() or 0\n\n                return {\n                    "total_users": total_users,\n                    "active_users": active_users,\n                    "total_sessions": total_sessions,\n                    "active_sessions": active_sessions,\n                    "service_status": "running" if self._initialized else "stopped",\n                    "tenant_id": str(tenant_uuid) if tenant_uuid is not None else None,\n                }\n        except Exception as exc:\n            logger.error("Failed to get auth stats: %s", exc)\n            return {\n                "total_users": 0,\n                "active_users": 0,\n                "total_sessions": 0,\n                "active_sessions": 0,\n                "service_status": "error",\n                "error": "Authentication statistics unavailable",\n            }\n\n'''
    service = service[:start] + replacement + service[end:]
    SERVICE.write_text(service, encoding="utf-8")


if __name__ == "__main__":
    main()
