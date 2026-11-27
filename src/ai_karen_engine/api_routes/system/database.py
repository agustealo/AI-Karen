"""
src/ai_karen_engine/api_routes/database.py
Database API routes for AI Karen.
Provides REST endpoints for tenant, memory, and conversation management.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg
from sqlalchemy.exc import OperationalError, ProgrammingError

from ai_karen_engine.auth.rbac_middleware import (
    Permission,
    require_platform_tenant_permission,
)
from ai_karen_engine.database.integration_manager import (
    DatabaseIntegrationManager,
    get_database_manager,
)
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Body, Depends, HTTPException, Path, Query = import_fastapi(
    "APIRouter", "Body", "Depends", "HTTPException", "Path", "Query"
)
BaseModel, Field, SecretStr, field_validator = import_pydantic(
    "BaseModel", "Field", "SecretStr", "field_validator"
)

logger = logging.getLogger(__name__)
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() == "true"

router = APIRouter(tags=["database"])


# ------------------------------------------------------------------------------
# Pydantic Models
# ------------------------------------------------------------------------------
class TenantCreateRequest(BaseModel):
    """Request model for creating a tenant."""

    name: str = Field(..., min_length=1, max_length=255, description="Tenant name")
    slug: str = Field(..., min_length=1, max_length=100, description="Tenant slug")
    admin_email: str = Field(..., description="Admin user email")
    admin_password: SecretStr = Field(..., description="Initial administrator password")
    admin_full_name: str = Field(..., min_length=1, max_length=255)
    subscription_tier: str = Field("basic", description="Subscription tier")
    settings: Optional[Dict[str, Any]] = Field(None, description="Additional settings")

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v):
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Slug must contain only alphanumeric characters, hyphens, and underscores"
            )
        return v.lower()


class TenantResponse(BaseModel):
    tenant_id: str
    name: str
    slug: str
    subscription_tier: str
    settings: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str


class TenantStatsResponse(BaseModel):
    tenant_id: str
    user_count: int
    conversation_count: int
    memory_entry_count: int
    plugin_execution_count: int
    storage_used_mb: float
    last_activity: Optional[str]
    created_at: str


class MemoryStoreRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Memory content")
    user_id: Optional[str] = Field(None, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    tags: Optional[List[str]] = Field(None, description="Memory tags")


class MemoryQueryRequest(BaseModel):
    query_text: str = Field(..., min_length=1, description="Query text")
    user_id: Optional[str] = Field(None, description="User ID filter")
    top_k: int = Field(10, ge=1, le=100, description="Number of results")
    similarity_threshold: float = Field(
        0.7, ge=0.0, le=1.0, description="Similarity threshold"
    )


class MemoryResponse(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any]
    timestamp: float
    ttl: Optional[str]
    user_id: Optional[str]
    session_id: Optional[str]
    tags: List[str]
    similarity_score: Optional[float]


class ConversationCreateRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    title: Optional[str] = Field(None, max_length=255, description="Conversation title")
    initial_message: Optional[str] = Field(None, description="Initial message")


class MessageAddRequest(BaseModel):
    role: str = Field(
        ..., description="Message role (user, assistant, system, function)"
    )
    content: str = Field(..., min_length=1, description="Message content")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Message metadata")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        valid = ["user", "assistant", "system", "function"]
        if v not in valid:
            raise ValueError(f"Role must be one of: {valid}")
        return v


class ConversationResponse(BaseModel):
    id: str
    user_id: str
    title: Optional[str]
    messages: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str
    message_count: int
    last_message_at: Optional[str]


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    components: Dict[str, Any]


# ------------------------------------------------------------------------------
# Dependencies
# ------------------------------------------------------------------------------
async def get_db_manager() -> DatabaseIntegrationManager:
    db = await get_database_manager()
    if not getattr(db, "_initialized", False) or not getattr(db, "db_client", None):
        logger.critical(
            "DatabaseIntegrationManager not initialized or missing db_client!"
        )
        raise HTTPException(
            status_code=500,
            detail="Database not initialized. Please check backend setup and run migrations.",
        )
    return db


# ------------------------------------------------------------------------------
# Schema status endpoint
# ------------------------------------------------------------------------------
@router.get("/schema/status", response_model=Dict[str, Any])
async def schema_status(
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Check that all required tables and migrations have been applied."""
    try:
        if db_manager.db_client is None:
            return {"success": False, "error": "Database client not initialized"}
        result = await db_manager.db_client.async_comprehensive_health_check()
        return {"success": True, "schema_status": result}
    except Exception as e:
        logger.critical(f"Schema status check failed: {e}")
        detail = str(e) if DEV_MODE else "Schema status unavailable"
        return {"success": False, "error": detail}


# ------------------------------------------------------------------------------
# Tenant Endpoints
# ------------------------------------------------------------------------------
@router.post("/tenants", response_model=Dict[str, Any], status_code=201)
async def create_tenant(
    request: TenantCreateRequest,
    current_user: Dict[str, Any] = Depends(
        require_platform_tenant_permission(Permission.ADMIN_TENANTS_MANAGE)
    ),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Create a new tenant through the governed administration service."""
    try:
        td = await db_manager.create_tenant(
            name=request.name,
            slug=request.slug,
            admin_email=request.admin_email,
            admin_password=request.admin_password.get_secret_value(),
            admin_full_name=request.admin_full_name,
            operator_id=current_user["user_id"],
            subscription_tier=request.subscription_tier,
            settings=request.settings,
        )
        logger.info(f"Created tenant: {td['tenant_id']}")
        return {"success": True, "message": "Tenant created successfully", "data": td}

    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ):
        logger.error("Tenant creation database unavailable")
        raise HTTPException(500, "Database unavailable") from None
    except ValueError:
        raise HTTPException(400, "Tenant or administrator creation rejected") from None
    except Exception as exc:
        logger.error("Tenant creation failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(500, "Tenant creation failed") from None


@router.get("/tenants/{tenant_id}", response_model=Dict[str, Any])
async def get_tenant(
    tenant_id: str = Path(..., description="Tenant ID"),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Get tenant information."""
    try:
        td = await db_manager.get_tenant(tenant_id)
        if not td:
            raise HTTPException(404, "Tenant not found")
        return {"success": True, "data": td}

    except HTTPException:
        raise
    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to get tenant {tenant_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


@router.get("/tenants/{tenant_id}/stats", response_model=Dict[str, Any])
async def get_tenant_stats(
    tenant_id: str = Path(..., description="Tenant ID"),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Get tenant statistics."""
    try:
        sd = await db_manager.get_tenant_stats(tenant_id)
        if not sd:
            raise HTTPException(404, "Tenant not found")
        return {"success": True, "data": sd}

    except HTTPException:
        raise
    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to get tenant stats {tenant_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


# ------------------------------------------------------------------------------
# Memory Endpoints
# ------------------------------------------------------------------------------
@router.post(
    "/tenants/{tenant_id}/memories", response_model=Dict[str, Any], status_code=201
)
async def store_memory(
    tenant_id: str = Path(..., description="Tenant ID"),
    request: MemoryStoreRequest = Body(...),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Store a memory entry."""
    try:
        mid = await db_manager.store_memory(
            tenant_id=tenant_id,
            content=request.content,
            user_id=request.user_id,
            session_id=request.session_id,
            metadata=request.metadata,
            tags=request.tags,
        )
        if not mid:
            return {
                "success": True,
                "message": "Not surprising enough, skipped",
                "data": None,
            }
        logger.info(f"Stored memory {mid} for tenant {tenant_id}")
        return {"success": True, "message": "Memory stored", "data": {"memory_id": mid}}

    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to store memory for tenant {tenant_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


@router.post("/tenants/{tenant_id}/memories/query", response_model=Dict[str, Any])
async def query_memories(
    tenant_id: str = Path(..., description="Tenant ID"),
    request: MemoryQueryRequest = Body(...),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Query memories with semantic search."""
    try:
        mems = await db_manager.query_memories(
            tenant_id=tenant_id,
            query_text=request.query_text,
            user_id=request.user_id,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
        )
        logger.info(f"Retrieved {len(mems)} memories for tenant {tenant_id}")
        return {"success": True, "data": {"memories": mems, "count": len(mems)}}

    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to query memories for tenant {tenant_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


# ------------------------------------------------------------------------------
# Conversation Endpoints
# ------------------------------------------------------------------------------
@router.post(
    "/tenants/{tenant_id}/conversations", response_model=Dict[str, Any], status_code=201
)
async def create_conversation(
    tenant_id: str = Path(..., description="Tenant ID"),
    request: ConversationCreateRequest = Body(...),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Create a new conversation."""
    try:
        cd = await db_manager.create_conversation(
            tenant_id=tenant_id,
            user_id=request.user_id,
            title=request.title,
            initial_message=request.initial_message,
        )
        logger.info(f"Created conversation {cd['id']} for tenant {tenant_id}")
        return {"success": True, "message": "Conversation created", "data": cd}

    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to create conversation for tenant {tenant_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


@router.get(
    "/tenants/{tenant_id}/conversations/{conversation_id}",
    response_model=Dict[str, Any],
)
async def get_conversation(
    tenant_id: str = Path(..., description="Tenant ID"),
    conversation_id: str = Path(..., description="Conversation ID"),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Get conversation with context."""
    try:
        cd = await db_manager.get_conversation(
            tenant_id=tenant_id, conversation_id=conversation_id
        )
        if not cd:
            raise HTTPException(404, "Conversation not found")
        return {"success": True, "data": cd}

    except HTTPException:
        raise
    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to get conversation {conversation_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


@router.post(
    "/tenants/{tenant_id}/conversations/{conversation_id}/messages",
    response_model=Dict[str, Any],
    status_code=201,
)
async def add_message(
    tenant_id: str = Path(..., description="Tenant ID"),
    conversation_id: str = Path(..., description="Conversation ID"),
    request: MessageAddRequest = Body(...),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Add a message to conversation."""
    try:
        md = await db_manager.add_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=request.role,
            content=request.content,
            metadata=request.metadata,
        )
        if not md:
            raise HTTPException(404, "Conversation not found")
        logger.info(f"Added message to conversation {conversation_id}")
        return {"success": True, "message": "Message added", "data": md}

    except HTTPException:
        raise
    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to add message to conversation {conversation_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


@router.get(
    "/tenants/{tenant_id}/users/{user_id}/conversations", response_model=Dict[str, Any]
)
async def list_conversations(
    tenant_id: str = Path(..., description="Tenant ID"),
    user_id: str = Path(..., description="User ID"),
    limit: int = Query(50, ge=1, le=100, description="Max number of conversations"),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """List conversations for a user."""
    try:
        convs = await db_manager.list_conversations(
            tenant_id=tenant_id, user_id=user_id, limit=limit
        )
        return {"success": True, "data": {"conversations": convs, "count": len(convs)}}

    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to list conversations for user {user_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


# ------------------------------------------------------------------------------
# Health & Monitoring
# ------------------------------------------------------------------------------
@router.get("/health", response_model=Dict[str, Any])
async def health_check(
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Perform comprehensive health check."""
    try:
        hd = await db_manager.health_check()
        return {"success": True, "data": hd}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "success": False,
            "data": {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
        }


@router.get("/metrics", response_model=Dict[str, Any])
async def get_metrics(db_manager: DatabaseIntegrationManager = Depends(get_db_manager)):
    """Get system metrics."""
    try:
        md = await db_manager.get_system_metrics()
        return {"success": True, "data": md}
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


@router.post("/maintenance", response_model=Dict[str, Any])
async def run_maintenance(
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Run maintenance tasks."""
    try:
        res = await db_manager.maintenance_tasks()
        return {"success": True, "message": "Maintenance completed", "data": res}
    except Exception as e:
        logger.error(f"Maintenance tasks failed: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


# ------------------------------------------------------------------------------
# Advanced Analytics & Bulk
# ------------------------------------------------------------------------------
@router.get("/tenants/{tenant_id}/analytics", response_model=Dict[str, Any])
async def get_tenant_analytics(
    tenant_id: str = Path(..., description="Tenant ID"),
    days: int = Query(30, ge=1, le=365, description="Period in days"),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Get tenant analytics data."""
    try:
        stats = await db_manager.get_tenant_stats(tenant_id)
        if not stats:
            raise HTTPException(404, "Tenant not found")
        analytics = {
            "tenant_id": tenant_id,
            "period_days": days,
            "basic_stats": stats,
            "trends": {
                "memory_growth": "stable",
                "conversation_activity": "increasing",
                "user_engagement": "high",
            },
            "recommendations": [
                "Upgrade to pro tier for better performance",
                "Enable advanced memory features for better context",
            ],
        }
        return {"success": True, "data": analytics}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get analytics for tenant {tenant_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)


@router.post("/tenants/{tenant_id}/memories/bulk", response_model=Dict[str, Any])
async def bulk_store_memories(
    tenant_id: str = Path(..., description="Tenant ID"),
    memories: List[MemoryStoreRequest] = Body(..., description="List of memories"),
    db_manager: DatabaseIntegrationManager = Depends(get_db_manager),
):
    """Bulk store multiple memories."""
    try:
        stored, skipped = [], 0
        for m in memories:
            mid = await db_manager.store_memory(
                tenant_id=tenant_id,
                content=m.content,
                user_id=m.user_id,
                session_id=m.session_id,
                metadata=m.metadata,
                tags=m.tags,
            )
            if mid:
                stored.append(mid)
            else:
                skipped += 1
        logger.info(
            f"Bulk stored {len(stored)} / skipped {skipped} for tenant {tenant_id}"
        )
        return {
            "success": True,
            "message": "Bulk storage completed",
            "data": {
                "stored_count": len(stored),
                "skipped_count": skipped,
                "stored_ids": stored,
            },
        }

    except (
        ProgrammingError,
        OperationalError,
        asyncpg.exceptions.UndefinedTableError,
    ) as e:
        logger.critical(f"Missing DB schema/table: {e}")
        raise HTTPException(500, "Database schema/table missing. Run migrations.")
    except Exception as e:
        logger.error(f"Failed to bulk store memories for tenant {tenant_id}: {e}")
        msg = str(e) if DEV_MODE else "Internal server error"
        raise HTTPException(500, msg)
