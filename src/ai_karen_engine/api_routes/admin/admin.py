from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ai_karen_engine.core.services.dependencies import get_memory_service
from ai_karen_engine.utils.bootstrap import bootstrap_memory_system

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


@router.post("/bootstrap_memory")
async def bootstrap_memory(
    request: Request,
    memory_service: Any = Depends(get_memory_service),
):
    """Force initialization of memory tables and default models for the active tenant."""
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id or str(tenant_id) == "default":
        raise HTTPException(
            status_code=403,
            detail="Explicit tenant scope is required for memory bootstrap",
        )

    try:
        success = await bootstrap_memory_system(
            memory_service,
            tenant_id=str(tenant_id),
        )
        return JSONResponse({"success": success})
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[%s] bootstrap failed: %s", trace_id, exc)
        raise HTTPException(status_code=500, detail="bootstrap failed") from exc
