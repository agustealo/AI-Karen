"""Runtime-owned durable human approval service."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from ai_karen_engine.audit_logging import (
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.persistence.repositories.approval_repository import (
    SqlApprovalRepository,
    get_approval_repository,
)


class ApprovalError(RuntimeError):
    """Base approval lifecycle error."""


class ApprovalNotFoundError(ApprovalError):
    """Approval does not exist in the caller's tenant/user scope."""


class ApprovalStateError(ApprovalError):
    """Approval cannot transition from its current state."""


class ApprovalScopeError(PermissionError):
    """Approval does not match the request attempting to consume it."""


def _identity(user: UserData) -> tuple[str, str]:
    user_id = str(user.user_id or "").strip()
    tenant_id = str(user.tenant_id or "").strip()
    if not user_id or not tenant_id or tenant_id == "default":
        raise ApprovalScopeError("Explicit authenticated user and tenant are required")
    return user_id, tenant_id


def request_fingerprint(request: ChatExecutionRequest) -> str:
    """Stable digest over execution-relevant request content.

    Correlation/request IDs and the approval token itself are intentionally
    excluded so an approved request may be resumed through a fresh transport
    attempt without permitting a changed request body.
    """
    payload = {
        "messages": request.messages,
        "tenant_id": request.context.tenant_id,
        "user_id": request.context.user_id,
        "conversation_id": request.context.conversation_id,
        "session_id": request.context.session_id,
        "preferred_provider": request.preferred_provider,
        "preferred_model": request.preferred_model,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": request.stream,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def serialize_request(request: ChatExecutionRequest) -> Dict[str, Any]:
    """Persist only the canonical normalized request needed for audited resume."""
    return {
        "messages": request.messages,
        "context": {
            "user_id": request.context.user_id,
            "tenant_id": request.context.tenant_id,
            "session_id": request.context.session_id,
            "conversation_id": request.context.conversation_id,
            "roles": list(request.context.roles),
            "permissions": list(request.context.permissions),
        },
        "preferred_provider": request.preferred_provider,
        "preferred_model": request.preferred_model,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": request.stream,
    }


class ApprovalService:
    """Lifecycle authority for pre-execution human approval receipts."""

    def __init__(
        self,
        repository: Optional[SqlApprovalRepository] = None,
    ) -> None:
        self._repository = repository or get_approval_repository()
        self._audit = get_audit_logger()

    async def create_for_request(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
    ) -> Dict[str, Any]:
        risk_level = getattr(decision.risk_level, "value", decision.risk_level)
        record = await self._repository.create(
            tenant_id=request.context.tenant_id,
            user_id=request.context.user_id,
            conversation_id=request.context.conversation_id,
            request_fingerprint=request_fingerprint(request),
            policy_decision_id=decision.policy_decision_id,
            intent=decision.intent,
            risk_level=str(risk_level),
            reason_codes=list(
                dict.fromkeys(
                    [
                        *decision.policy_reason_codes,
                        *decision.reason_codes,
                    ]
                )
            ),
            request_payload=serialize_request(request),
        )
        self._audit.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT,
                "severity": AuditSeverity.INFO,
                "message": "runtime_approval_requested",
                "user_id": request.context.user_id,
                "tenant_id": request.context.tenant_id,
                "session_id": request.context.session_id,
                "correlation_id": request.context.correlation_id,
                "metadata": {
                    "approval_id": record["approval_id"],
                    "intent": decision.intent,
                    "risk_level": str(risk_level),
                    "policy_decision_id": decision.policy_decision_id,
                },
            }
        )
        return record

    async def list_pending(self, *, user: UserData) -> List[Dict[str, Any]]:
        user_id, tenant_id = _identity(user)
        return await self._repository.list_pending(
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def get(self, approval_id: str, *, user: UserData) -> Dict[str, Any]:
        user_id, tenant_id = _identity(user)
        record = await self._repository.get(
            approval_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if record is None:
            raise ApprovalNotFoundError("Approval not found")
        return record

    async def decide(
        self,
        approval_id: str,
        *,
        user: UserData,
        decision: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        user_id, tenant_id = _identity(user)
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approved", "rejected"}:
            raise ApprovalStateError("Decision must be approved or rejected")
        record = await self._repository.decide(
            approval_id,
            tenant_id=tenant_id,
            user_id=user_id,
            decision=normalized,
            reason=(reason or "").strip() or None,
            decided_by=user_id,
        )
        if record is None:
            current = await self._repository.get(
                approval_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            if current is None:
                raise ApprovalNotFoundError("Approval not found")
            raise ApprovalStateError(
                f"Approval cannot be decided from status {current['status']}"
            )

        self._audit.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT,
                "severity": AuditSeverity.INFO,
                "message": "runtime_approval_decided",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "metadata": {
                    "approval_id": approval_id,
                    "decision": normalized,
                },
            }
        )
        return record

    async def consume_for_request(
        self,
        approval_id: str,
        *,
        request: ChatExecutionRequest,
    ) -> Dict[str, Any]:
        record = await self._repository.consume_approved(
            approval_id,
            tenant_id=request.context.tenant_id,
            user_id=request.context.user_id,
            request_fingerprint=request_fingerprint(request),
        )
        if record is None:
            current = await self._repository.get(
                approval_id,
                tenant_id=request.context.tenant_id,
                user_id=request.context.user_id,
            )
            if current is None:
                raise ApprovalNotFoundError("Approval not found")
            if current["request_fingerprint"] != request_fingerprint(request):
                raise ApprovalScopeError("Approval does not match this request")
            raise ApprovalStateError(
                f"Approval cannot be consumed from status {current['status']}"
            )

        self._audit.log_audit_event(
            {
                "event_type": AuditEventType.SECURITY_EVENT,
                "severity": AuditSeverity.INFO,
                "message": "runtime_approval_consumed",
                "user_id": request.context.user_id,
                "tenant_id": request.context.tenant_id,
                "session_id": request.context.session_id,
                "correlation_id": request.context.correlation_id,
                "metadata": {
                    "approval_id": approval_id,
                    "original_policy_decision_id": record.get(
                        "policy_decision_id"
                    ),
                },
            }
        )
        return record


_approval_service: Optional[ApprovalService] = None


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service


__all__ = [
    "ApprovalError",
    "ApprovalNotFoundError",
    "ApprovalScopeError",
    "ApprovalService",
    "ApprovalStateError",
    "get_approval_service",
    "request_fingerprint",
    "serialize_request",
]
