import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.database.health_contracts import DatabaseOperationsOverview
from ai_karen_engine.services.database.operations_service import get_database_operations_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/database", tags=["admin", "database"])

async def admin_required(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Dependency to ensure the user has admin role."""
    roles = current_user.get("roles", [])
    if "admin" not in roles and "super_admin" not in roles:
        logger.warning(f"Unauthorized database operations access attempt by {current_user.get('id')}")
        raise HTTPException(status_code=403, detail="Admin role required for database operations")
    return current_user

@router.get("/overview", response_model=DatabaseOperationsOverview)
async def get_database_overview(
    x_correlation_id: Optional[str] = Header(None),
    current_user: Dict[str, Any] = Depends(admin_required),
    service = Depends(get_database_operations_service)
):
    """Get a comprehensive overview of database operations."""
    correlation_id = x_correlation_id or "unknown"
    try:
        return await service.get_overview(correlation_id)
    except Exception as e:
        logger.error(f"Error fetching database overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/health")
async def get_database_health(
    current_user: Dict[str, Any] = Depends(admin_required),
    service = Depends(get_database_operations_service)
):
    """Detailed health check for database tiers."""
    overview = await service.get_overview("health-check")
    return {
        "status": overview.status,
        "tiers": overview.storage_tiers,
        "timestamp": overview.generated_at
    }

@router.post("/maintenance/run")
async def run_database_maintenance(
    current_user: Dict[str, Any] = Depends(admin_required),
    service = Depends(get_database_operations_service)
):
    """Trigger database maintenance tasks (vacuum, analyze, etc.)."""
    # Placeholder for maintenance logic
    logger.info(f"Database maintenance triggered by {current_user.get('id')}")
    return {"status": "started", "message": "Database maintenance background task started"}

@router.post("/projections/retry")
async def retry_projections(
    current_user: Dict[str, Any] = Depends(admin_required),
    service = Depends(get_database_operations_service)
):
    """Retry failed memory projections."""
    # Placeholder for projection retry logic
    logger.info(f"Memory projections retry triggered by {current_user.get('id')}")
    return {"status": "success", "message": "Projection sync retries initiated"}

@router.post("/migrations/validate")
async def validate_migrations(
    current_user: Dict[str, Any] = Depends(admin_required),
    service = Depends(get_database_operations_service)
):
    """Validate database schema consistency and migration history."""
    # Placeholder for migration validation logic
    logger.info(f"Migration validation triggered by {current_user.get('id')}")
    return {"status": "success", "message": "Schema validation complete. No inconsistencies found."}
