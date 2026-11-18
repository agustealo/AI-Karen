"""Owner-scoped Communications Center observability ingress.

This view is a consumer projection, not the administrator audit reader. The
underlying loggers buffer process-wide events, so nothing from those buffers may
leave this route without an exact authenticated tenant and user match.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from ai_karen_engine.core.services.dependencies import get_user_context
from ai_karen_engine.core.services.service_registry import get_service_registry
from ai_karen_engine.services.audit.audit_logging import get_audit_logger
from ai_karen_engine.services.audit.training_audit_logger import get_training_audit_logger


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


def _event_type(value: Any) -> str:
    original = getattr(value, "value", value)
    return str(original)[:100] if original is not None else "unknown"


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
