"""Owner-scoped Communications Center observability ingress.

This view is a consumer projection, not the administrator audit reader. The
underlying loggers buffer process-wide events, so nothing from those buffers may
leave this route without an exact authenticated tenant and user match.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.auth_middleware import AuthenticationError
from ai_karen_engine.core.realtime.inbox_invalidation import InboxInvalidationUnavailable
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.services.dependencies import get_user_context
from ai_karen_engine.middleware.correlation_middleware import get_request_correlation_id
from ai_karen_engine.persistence.repositories.communications_inbox_repository import (
    InboxConflict, InboxCursor, InboxEntry, InboxFilter, InboxNotFound, InboxOperation,
)
from ai_karen_engine.services.communications_inbox import (
    CommunicationsAuthorizationError, CommunicationsInboxService, CommunicationsProducerUnavailable,
)
from ai_karen_engine.core.services.service_registry import get_service_registry
from ai_karen_engine.services.audit.audit_logging import AuditEventType, get_audit_logger
from ai_karen_engine.services.audit.training_audit_logger import TrainingEventType, get_training_audit_logger


logger = logging.getLogger(__name__)
router = APIRouter(tags=["communications-center"])


def _owned_by(event: Any, *, tenant_id: str, user_id: str) -> bool:
    """Unattributed and cross-principal events are never consumer-readable."""
    if isinstance(event, dict):
        event_tenant = event.get("tenant_id")
        event_user = event.get("user_id")
    else:
        event_tenant = getattr(event, "tenant_id", None)
        event_user = getattr(event, "user_id", None)
    return event_tenant == tenant_id and event_user == user_id


def _event_timestamp(value: Any) -> str | None:
    """Keep only valid, timezone-aware timestamps in the public projection."""
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else None
        )
        if parsed is None or parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


# Display labels are sourced only from canonical event contracts. Arbitrary
# producer-supplied type/subtype strings may contain secrets or internal paths.
# Keep unrecognized events countable without reflecting their raw identifiers.
_PUBLIC_EVENT_TYPES = frozenset(event.value for event in AuditEventType) | frozenset(
    event.value for event in TrainingEventType
) | {"training_operation"}


def _event_type(value: Any) -> str:
    original = getattr(value, "value", value)
    return original if isinstance(original, str) and original in _PUBLIC_EVENT_TYPES else "unclassified_event"


def _display_event(event: Any) -> Dict[str, Any]:
    if isinstance(event, dict):
        event_type = event.get("event_type")
        timestamp = event.get("timestamp")
    else:
        event_type = getattr(event, "event_type", None)
        timestamp = getattr(event, "timestamp", None)
    label = _event_type(event_type)
    # Audit messages are unrestricted producer strings, and can contain raw
    # exception text or credentials. This consumer projection must not echo
    # them, even when the original event belongs to the requesting principal.
    return {
        "event_type": label,
        "message": "Audit event" if label == "unknown" else label,
        "timestamp": _event_timestamp(timestamp),
    }


@router.get("/observability")
async def get_communications_center_observability(
    current_user: Dict[str, Any] = Depends(get_user_context),
) -> Dict[str, Any]:
    """Return identity-scoped audit evidence without leaking global diagnostics."""
    user_id = str(current_user.get("user_id") or "").strip()
    tenant_id = str(current_user.get("tenant_id") or "").strip()
    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Authenticated identity scope required")

    generated_at = datetime.now(timezone.utc).isoformat()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # The canonical AuditLogger buffer is process-wide. Filter before selection
    # and derive counts from the same owned snapshot, never global counters.
    raw_audit_events = get_audit_logger().get_recent_events(limit=1000)
    scoped_audit_events = [
        event
        for event in raw_audit_events
        if isinstance(event, dict)
        and _owned_by(event, tenant_id=tenant_id, user_id=user_id)
    ]
    selected_audit = scoped_audit_events[-25:]
    audit_events = [_display_event(event) for event in selected_audit]
    audit_counts: Dict[str, int] = {}
    for event in selected_audit:
        key = _event_type(event.get("event_type"))
        audit_counts[key] = audit_counts.get(key, 0) + 1

    # TrainingAuditLogger's cumulative counts and security list are also
    # process-wide. Only scoped audit receipts contribute to user-level counts.
    training_counts: Dict[str, int] = {}
    for event in scoped_audit_events:
        if event.get("event_type") != "training_operation":
            continue
        timestamp = _event_timestamp(event.get("timestamp"))
        if timestamp is None or datetime.fromisoformat(timestamp) < cutoff:
            continue
        metadata = event.get("metadata")
        subtype = (
            metadata.get("training_event_type")
            if isinstance(metadata, dict)
            else None
        )
        kind = _event_type(subtype) if subtype else "training_operation"
        training_counts[kind] = training_counts.get(kind, 0) + 1

    training_security_events = [
        _display_event(event)
        for event in get_training_audit_logger().get_security_events(hours=24)
        if _owned_by(event, tenant_id=tenant_id, user_id=user_id)
        and (timestamp := _event_timestamp(getattr(event, "timestamp", None)))
        and datetime.fromisoformat(timestamp) >= cutoff
    ]

    # No user-level queue or shard-link counts are exposed by the canonical
    # memory service. Never reuse process-wide service_metrics as personal data.
    memory_observability: Dict[str, Any] = {
        "available": False,
        "pending_writebacks": 0,
        "active_shard_links": 0,
        "feedback_metrics": {},
        "service_metrics": {},
    }
    alerts: List[Dict[str, Any]] = []

    try:
        service = await get_service_registry().get_service("memory_service")
        if service is not None and hasattr(service, "get_writeback_feedback_metrics"):
            # This canonical method enforces user/org filters at retrieval.
            metrics = await service.get_writeback_feedback_metrics(
                user_id=user_id, org_id=tenant_id, time_window_hours=24,
            )
            if is_dataclass(metrics) and not isinstance(metrics, type):
                metrics = asdict(metrics)
            if isinstance(metrics, dict):
                memory_observability["feedback_metrics"] = metrics
    except Exception as exc:
        logger.warning(
            "Communications Center scoped memory feedback unavailable: %s",
            type(exc).__name__,
        )
        alerts.append({
            "id": "memory-feedback-unavailable",
            "title": "Memory feedback unavailable",
            "description": "Account-scoped memory feedback could not be verified.",
            "type": "warning",
            "timestamp": generated_at,
        })

    if training_security_events:
        alerts.append({
            "id": "training-security-events",
            "title": "Training security events present",
            "description": (
                f"{len(training_security_events)} account-scoped training "
                "security event(s) were recorded in the last 24 hours."
            ),
            "type": "warning",
            "timestamp": generated_at,
        })

    # Do not issue a blanket "system healthy" notification. Audit buffers,
    # training counters and memory writeback status are not global health proof.
    return {
        "generated_at": generated_at,
        "audit": {"recent_events": audit_events, "event_counts": audit_counts},
        "training": {
            "event_counts": training_counts,
            "security_events": training_security_events,
        },
        "memory": memory_observability,
        "alerts": alerts,
    }


class InboxEntryResponse(BaseModel):
    entry_id: UUID
    conversation_id: UUID
    execution_id: UUID
    source_kind: Literal["terminal_chat_attention"]
    source_status: Literal["failed", "orphaned"]
    created_at: datetime
    read_at: datetime | None
    acknowledged_at: datetime | None
    archived_at: datetime | None
    # Preserve the full PostgreSQL bigint without JavaScript number rounding.
    revision: str


class InboxCursorResponse(BaseModel):
    created_at: datetime
    entry_id: UUID


class InboxCapabilitiesResponse(BaseModel):
    can_mutate: bool
    producer_enabled: bool
    can_reconcile: bool
    invalidation_wait_enabled: bool = False


class InboxPageResponse(BaseModel):
    entries: list[InboxEntryResponse]
    next_cursor: InboxCursorResponse | None
    active_unread_count: int
    capabilities: InboxCapabilitiesResponse


class InboxMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: InboxOperation
    expected_revision: str = Field(strict=True, pattern=r"^[1-9][0-9]{0,18}$")


class InboxMutationResponse(BaseModel):
    entry: InboxEntryResponse
    changed: bool


def _inbox_entry_response(entry: InboxEntry) -> InboxEntryResponse:
    return InboxEntryResponse.model_validate({**asdict(entry), "revision": str(entry.revision)})


def get_communications_inbox_service() -> CommunicationsInboxService:
    return CommunicationsInboxService()


def _inbox_error(exc: Exception, correlation_id: str) -> HTTPException:
    if isinstance(exc, CommunicationsAuthorizationError):
        return HTTPException(status_code=403, detail="Communications permission denied")
    if isinstance(exc, CommunicationsProducerUnavailable):
        return HTTPException(status_code=503, detail="Communications producer unavailable")
    if isinstance(exc, InboxNotFound):
        return HTTPException(status_code=404, detail="Communications entry not found")
    if isinstance(exc, InboxConflict):
        return HTTPException(status_code=409, detail="Communications revision conflict")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail="Invalid communications request")
    logger.error("communications.inbox.unavailable", extra={
        "correlation_id": correlation_id, "error_type": type(exc).__name__,
    })
    return HTTPException(status_code=503, detail="Communications inbox unavailable")


@router.get("/inbox", response_model=InboxPageResponse)
async def list_communications_inbox(
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    inbox_filter: InboxFilter = Query(default=InboxFilter.ACTIVE),
    cursor_at: datetime | None = Query(default=None),
    cursor_id: UUID | None = Query(default=None),
    user: UserData = Depends(get_current_user),
    service: CommunicationsInboxService = Depends(get_communications_inbox_service),
) -> InboxPageResponse:
    correlation_id = get_request_correlation_id(request)
    if (cursor_at is None) != (cursor_id is None):
        raise HTTPException(status_code=422, detail="Complete inbox cursor required")
    cursor = None
    if cursor_at is not None and cursor_id is not None:
        if cursor_at.utcoffset() is None:
            raise HTTPException(status_code=422, detail="Timezone-aware inbox cursor required")
        cursor = InboxCursor(cursor_at, str(cursor_id))
    try:
        owned = await service.list_owned(
            user=user, correlation_id=correlation_id, limit=limit,
            inbox_filter=inbox_filter, cursor=cursor,
        )
        page = owned.page
        response.headers["Cache-Control"] = "no-store"
        return InboxPageResponse(
            entries=[_inbox_entry_response(entry) for entry in page.entries],
            next_cursor=InboxCursorResponse.model_validate(asdict(page.next_cursor))
            if page.next_cursor else None,
            active_unread_count=page.active_unread_count,
            capabilities=InboxCapabilitiesResponse.model_validate(asdict(owned.capabilities)),
        )
    except Exception as exc:
        raise _inbox_error(exc, correlation_id) from None


class InboxInvalidationResponse(BaseModel):
    changed: bool


@router.get("/inbox/wait", response_model=InboxInvalidationResponse)
async def wait_communications_inbox(
    request: Request,
    response: Response,
    user: UserData = Depends(get_current_user),
    service: CommunicationsInboxService = Depends(get_communications_inbox_service),
) -> InboxInvalidationResponse:
    """Bounded change hint, never a notification read or execution request."""
    headers = {"Cache-Control": "no-store"}
    if request.query_params:
        raise HTTPException(status_code=422, detail="Inbox wait accepts no parameters", headers=headers)
    correlation_id = get_request_correlation_id(request)

    async def reauthenticate() -> UserData:
        # Canonical session helper authenticates the original request again;
        # it does not trust request.state.user or the initial dependency result.
        return await get_current_user(request, credentials=None)

    try:
        changed = await service.wait_owned(
            user=user, correlation_id=correlation_id,
            reauthenticate=reauthenticate, disconnected=request.is_disconnected,
        )
        response.headers.update(headers)
        return InboxInvalidationResponse(changed=changed)
    except AuthenticationError as exc:
        code = exc.status_code if exc.status_code in (401, 403, 429, 503) else 503
        raise HTTPException(status_code=code, detail="Active session unavailable", headers=headers) from None
    except HTTPException as exc:
        code = exc.status_code if exc.status_code in (401, 403, 429, 503) else 503
        raise HTTPException(status_code=code, detail="Active session unavailable", headers=headers) from None
    except InboxInvalidationUnavailable:
        raise HTTPException(status_code=503, detail="Inbox invalidation unavailable", headers=headers) from None
    except Exception as exc:
        error = _inbox_error(exc, correlation_id)
        error.headers = headers
        raise error from None


@router.patch("/inbox/{entry_id}", response_model=InboxMutationResponse)
async def mutate_communications_inbox(
    entry_id: UUID,
    payload: InboxMutationRequest,
    request: Request,
    user: UserData = Depends(get_current_user),
    service: CommunicationsInboxService = Depends(get_communications_inbox_service),
) -> InboxMutationResponse:
    correlation_id = get_request_correlation_id(request)
    try:
        result = await service.mutate_owned(
            user=user, correlation_id=correlation_id, entry_id=entry_id,
            operation=payload.operation, expected_revision=int(payload.expected_revision),
        )
        return InboxMutationResponse(entry=_inbox_entry_response(result.entry), changed=result.changed)
    except Exception as exc:
        raise _inbox_error(exc, correlation_id) from None


class InboxReconciliationResponse(BaseModel):
    # This is only the count committed by this bounded operation, not proof
    # that the entire queue has been drained or a notification was delivered.
    admitted_count: int


@router.post("/inbox/reconcile", response_model=InboxReconciliationResponse)
async def reconcile_communications_inbox(
    request: Request,
    user: UserData = Depends(get_current_user),
    service: CommunicationsInboxService = Depends(get_communications_inbox_service),
) -> InboxReconciliationResponse:
    correlation_id = get_request_correlation_id(request)
    try:
        count = await service.reconcile_owned(user=user, correlation_id=correlation_id)
        return InboxReconciliationResponse(admitted_count=count)
    except Exception as exc:
        raise _inbox_error(exc, correlation_id) from None
