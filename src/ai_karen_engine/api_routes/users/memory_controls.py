"""Retired, unmounted compatibility surface for legacy user memory controls.

The canonical application registry does not mount this router. Do not reinstate
these endpoints without a governed backend implementing authenticated, durable
memory inspection, correction, deletion, and erasure receipts.

Keeping fail-closed handlers prevents callers that import this old module from
receiving fabricated success while a full reference audit is completed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ai_karen_engine.core.services.dependencies import UserContext_Dep

router = APIRouter(prefix="/users/memory", tags=["memory-controls"])


class MemoryItem(BaseModel):
    id: uuid.UUID
    content: str
    confidence: float
    memory_type: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateMemoryRequest(BaseModel):
    content: str | None = None
    is_correct: bool | None = None


def _retired_memory_control() -> None:
    """Fail closed until a canonical owner can verify the actual operation."""
    raise HTTPException(
        status_code=503,
        detail="Legacy memory controls unavailable; no memory operation was performed.",
    )


@router.get("/inspect", response_model=list[MemoryItem])
async def inspect_memory(
    user_ctx: dict[str, Any] = UserContext_Dep,
    memory_type: str | None = Query(None, pattern="^(assertion|fact)$"),
) -> list[MemoryItem]:
    """An empty response must not masquerade as an authoritative memory view."""
    _retired_memory_control()
    raise AssertionError("unreachable")


@router.patch("/{memory_id}")
async def correct_memory(
    memory_id: uuid.UUID,
    request: UpdateMemoryRequest,
    user_ctx: dict[str, Any] = UserContext_Dep,
) -> None:
    """Never acknowledge an uncommitted memory correction."""
    _retired_memory_control()


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: uuid.UUID,
    user_ctx: dict[str, Any] = UserContext_Dep,
) -> None:
    """Never acknowledge an uncommitted memory deletion."""
    _retired_memory_control()


@router.post("/forget-all")
async def forget_everything(
    user_ctx: dict[str, Any] = UserContext_Dep,
) -> None:
    """Never claim erasure without canonical durable verification."""
    _retired_memory_control()
