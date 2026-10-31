"""Thin, authenticated HTTP ingress for durable personal countdowns.

A stored countdown deadline is not a promise of background notifications.
All identity, authorization, auditing and persistence are delegated.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.middleware.correlation_middleware import get_request_correlation_id
from ai_karen_engine.services.automation.timers import (
    OwnedTimerService,
    TimerAuthorizationError,
    TimerNotFoundError,
)


router = APIRouter(prefix="/api/timers", tags=["personal-timers"])


class TimerCreateRequest(BaseModel):
    duration_seconds: int = Field(ge=1, le=86400)
    title: str = Field(default="Timer", min_length=1, max_length=240)
    idempotency_key: UUID


class TimerReceipt(BaseModel):
    timer_id: UUID
    duration_seconds: int
    title: str
    status: str
    started_at: datetime
    deadline_at: datetime
    cancelled_at: datetime | None
    observed_at: datetime
    scheduler_source: str
    durable: bool
    reminder_scheduled: bool
    notification_delivered: bool


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TimerAuthorizationError):
        return HTTPException(status_code=403, detail="Timer permission denied")
    if isinstance(exc, TimerNotFoundError):
        return HTTPException(status_code=404, detail="Timer not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail="Timer request conflict or invalid data")
    raise exc


@router.post("/", response_model=TimerReceipt, status_code=201)
async def create_timer(
    payload: TimerCreateRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TimerReceipt:
    try:
        snapshot = await OwnedTimerService().create(
            user=user,
            duration_seconds=payload.duration_seconds,
            title=payload.title,
            idempotency_key=payload.idempotency_key,
            correlation_id=get_request_correlation_id(request),
        )
        return TimerReceipt(**snapshot)
    except (TimerAuthorizationError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/", response_model=list[TimerReceipt])
async def list_timers(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user: UserData = Depends(get_current_user),
) -> list[TimerReceipt]:
    try:
        rows = await OwnedTimerService().list(
            user=user, correlation_id=get_request_correlation_id(request), limit=limit,
        )
        return [TimerReceipt(**row) for row in rows]
    except TimerAuthorizationError as exc:
        raise _http_error(exc) from exc


@router.get("/{timer_id}", response_model=TimerReceipt)
async def get_timer(
    timer_id: UUID,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TimerReceipt:
    try:
        row = await OwnedTimerService().get(
            user=user, timer_id=timer_id, correlation_id=get_request_correlation_id(request),
        )
        return TimerReceipt(**row)
    except (TimerAuthorizationError, TimerNotFoundError) as exc:
        raise _http_error(exc) from exc


@router.delete("/{timer_id}", response_model=TimerReceipt)
async def cancel_timer(
    timer_id: UUID,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> TimerReceipt:
    try:
        row = await OwnedTimerService().cancel(
            user=user, timer_id=timer_id, correlation_id=get_request_correlation_id(request),
        )
        return TimerReceipt(**row)
    except (TimerAuthorizationError, TimerNotFoundError) as exc:
        raise _http_error(exc) from exc
