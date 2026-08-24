from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from ai_karen_engine.utils.dependency_checks import import_fastapi

APIRouter = import_fastapi("APIRouter")

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system-status"])


@router.get("/status")
async def get_public_system_status():
    """Return basic public system status (no admin required)."""
    try:
        from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
            get_chat_runtime_control_plane,
        )
        control_plane = await get_chat_runtime_control_plane()
        snapshot = control_plane.get_snapshot()

        deps = {}
        for name, health in snapshot.dependencies.items():
            deps[name] = {
                "status": health.status.value,
                "response_time_ms": health.response_time_ms,
            }

        return {
            "status": "ok" if snapshot.normal_ready else "degraded",
            "mode": snapshot.mode.value,
            "maintenance_active": snapshot.maintenance_active,
            "expression_engine": {
                "active": snapshot.mode.value,
                "healthy": snapshot.normal_ready,
                "fallback_level": 0 if snapshot.normal_ready else 1,
                "degraded": not snapshot.normal_ready,
            },
            "memory": {
                "status": "ok" if snapshot.normal_ready else "degraded",
                "usage_percent": 0,
            },
            "plugins": {
                "active": 0,
                "failed": 0,
            },
            "dependencies": deps,
        }
    except Exception as exc:
        logger.debug("Public system status unavailable: %s", exc)
        return {
            "status": "unknown",
            "mode": "unknown",
            "maintenance_active": False,
            "expression_engine": {"active": "unknown", "healthy": False, "fallback_level": 0, "degraded": False},
            "memory": {"status": "unknown", "usage_percent": 0},
            "plugins": {"active": 0, "failed": 0},
            "dependencies": {},
        }


@router.get("/health")
async def get_public_health_summary():
    """Return basic public health summary (no admin required)."""
    try:
        from ai_karen_engine.core.model_runtime.provider_registry_service import (
            get_provider_registry_service,
        )
        registry = get_provider_registry_service()
        provider_names = registry.list_providers()
        healthy = registry.get_healthy_providers()

        return {
            "providers": {
                "total": len(provider_names),
                "healthy": len(healthy),
            }
        }
    except Exception as exc:
        logger.debug("Public health summary unavailable: %s", exc)
        return {"providers": {"total": 0, "healthy": 0}}


@router.get("/database/health")
async def get_public_database_health():
    """Return basic public database health (no admin required)."""
    try:
        from ai_karen_engine.database.client import get_database_client
        db_client = get_database_client()
        health = db_client.health_check()
        return {
            "status": health.get("status", "unknown"),
            "total_operations": 0,
        }
    except Exception as exc:
        logger.debug("Public database health unavailable: %s", exc)
        return {"status": "unknown", "total_operations": 0}
