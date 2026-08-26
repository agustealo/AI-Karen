from __future__ import annotations

from fastapi import FastAPI

from ai_karen_engine.api_routes.admin.admin import router as admin_router
from ai_karen_engine.api_routes.admin.diagnostics import router as admin_diagnostics_router
from ai_karen_engine.api_routes.admin.users import router as admin_users_router
from ai_karen_engine.api_routes.admin.tenants import router as admin_tenants_router
from ai_karen_engine.api_routes.admin.providers import router as admin_providers_router
from ai_karen_engine.api_routes.admin.plugins import router as admin_plugins_router
from ai_karen_engine.api_routes.admin.audit import router as admin_audit_router
from ai_karen_engine.api_routes.admin.health import router as admin_health_router
from ai_karen_engine.api_routes.admin.runtime import router as admin_runtime_router
from ai_karen_engine.api_routes.admin.features import router as admin_features_router
from ai_karen_engine.api_routes.admin.memory import router as admin_memory_router


def register_admin_endpoints(app: FastAPI, settings=None) -> None:
    """Register admin endpoints on the FastAPI app."""
    app.include_router(admin_router)
    app.include_router(admin_users_router, prefix="/api", tags=["admin-users"])
    app.include_router(admin_tenants_router, prefix="/api", tags=["admin-tenants"])
    app.include_router(admin_providers_router, prefix="/api", tags=["admin-providers"])
    app.include_router(admin_plugins_router, prefix="/api", tags=["admin-plugins"])
    app.include_router(admin_audit_router, prefix="/api", tags=["admin-audit"])
    app.include_router(admin_health_router, prefix="/api", tags=["admin-health"])
    app.include_router(admin_runtime_router, prefix="/api", tags=["admin-runtime"])
    app.include_router(admin_diagnostics_router, prefix="/api", tags=["admin-diagnostics"])
    app.include_router(admin_features_router, prefix="/api", tags=["admin-features"])
    app.include_router(admin_memory_router, prefix="/api", tags=["admin-memory"])


__all__ = ["register_admin_endpoints"]
