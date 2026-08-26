from __future__ import annotations

import logging
import uuid

from ai_karen_engine.core.memory.unified_memory_service import (
    MemoryCommitRequest,
    MemoryQueryRequest,
    UnifiedMemoryService,
)
from ai_karen_engine.core.model_runtime.default_models import load_default_models

logger = logging.getLogger(__name__)


async def bootstrap_memory_system(
    memory_service: UnifiedMemoryService,
    *,
    tenant_id: str,
) -> bool:
    """Ensure memory storage is initialized and prove a unified round trip."""
    if not tenant_id or tenant_id == "default":
        raise ValueError("bootstrap memory requires an explicit non-default tenant_id")

    base_manager = memory_service.base_manager
    if base_manager is None or getattr(base_manager, "db_client", None) is None:
        raise RuntimeError("canonical unified memory service is not storage-backed")

    db_client = base_manager.db_client
    if not db_client.ensure_memory_table(tenant_id):
        logger.error("[bootstrap] failed to ensure memory table for %s", tenant_id)
        return False

    await load_default_models()

    user_id = str(uuid.uuid4())
    commit_response = await memory_service.commit(
        tenant_id=tenant_id,
        request=MemoryCommitRequest(
            user_id=user_id,
            org_id=None,
            text="bootstrap test",
            tags=["bootstrap"],
            importance=5,
            decay="short",
            metadata={"source": "bootstrap"},
        ),
    )
    search_response = await memory_service.query(
        tenant_id=tenant_id,
        request=MemoryQueryRequest(
            user_id=user_id,
            org_id=None,
            query="bootstrap test",
            top_k=10,
            similarity_threshold=0.0,
            include_metadata=True,
        ),
    )
    found = any(hit.id == commit_response.id for hit in search_response.hits)
    logger.info("[bootstrap] roundtrip success=%s", found)
    return found
