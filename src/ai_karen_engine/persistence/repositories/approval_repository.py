"""Durable repository for Runtime-owned human approval receipts."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

_APPROVAL_TTL_MINUTES = 30


def _row(row: Any) -> Dict[str, Any]:
    data = dict(row)
    return {
        "approval_id": str(data["approval_id"]),
        "tenant_id": str(data["tenant_id"]),
        "user_id": str(data["user_id"]),
        "conversation_id": (
            str(data["conversation_id"]) if data.get("conversation_id") else None
        ),
        "request_fingerprint": data["request_fingerprint"],
        "policy_decision_id": data.get("policy_decision_id"),
        "intent": data["intent"],
        "risk_level": data["risk_level"],
        "reason_codes": list(data.get("reason_codes") or []),
        "request_payload": dict(data.get("request_payload") or {}),
        "status": data["status"],
        "decision_reason": data.get("decision_reason"),
        "decided_by": (
            str(data["decided_by"]) if data.get("decided_by") else None
        ),
        "created_at": data["created_at"],
        "expires_at": data["expires_at"],
        "decided_at": data.get("decided_at"),
        "consumed_at": data.get("consumed_at"),
        "updated_at": data["updated_at"],
    }


class SqlApprovalRepository:
    """Single durable source of truth for human approval lifecycle."""

    async def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: Optional[str],
        request_fingerprint: str,
        policy_decision_id: Optional[str],
        intent: str,
        risk_level: str,
        reason_codes: List[str],
        request_payload: Dict[str, Any],
        ttl_minutes: int = _APPROVAL_TTL_MINUTES,
    ) -> Dict[str, Any]:
        approval_id = uuid.uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, ttl_minutes))
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO public.runtime_approval_requests (
                        approval_id, tenant_id, user_id, conversation_id,
                        request_fingerprint, policy_decision_id, intent,
                        risk_level, reason_codes, request_payload, expires_at
                    ) VALUES (
                        :approval_id, CAST(:tenant_id AS uuid), CAST(:user_id AS uuid),
                        CAST(:conversation_id AS uuid), :request_fingerprint,
                        :policy_decision_id, :intent, :risk_level,
                        CAST(:reason_codes AS jsonb), CAST(:request_payload AS jsonb),
                        :expires_at
                    )
                    RETURNING *
                    """
                ),
                {
                    "approval_id": approval_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "request_fingerprint": request_fingerprint,
                    "policy_decision_id": policy_decision_id,
                    "intent": intent,
                    "risk_level": risk_level,
                    "reason_codes": json.dumps(reason_codes),
                    "request_payload": json.dumps(request_payload),
                    "expires_at": expires_at,
                },
            )
            return _row(result.mappings().one())

    async def get(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE public.runtime_approval_requests
                    SET status = 'expired',
                        request_payload = '{}'::jsonb,
                        updated_at = now()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                      AND status IN ('pending', 'approved')
                      AND expires_at <= now()
                    """
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM public.runtime_approval_requests
                    WHERE approval_id = CAST(:approval_id AS uuid)
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                    """
                ),
                {
                    "approval_id": approval_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )
            row = result.mappings().one_or_none()
            return _row(row) if row else None

    async def list_pending(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        async with async_transaction_scope(tenant_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE public.runtime_approval_requests
                    SET status = 'expired',
                        request_payload = '{}'::jsonb,
                        updated_at = now()
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                      AND status IN ('pending', 'approved')
                      AND expires_at <= now()
                    """
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM public.runtime_approval_requests
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                      AND status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "limit": max(1, min(limit, 100)),
                },
            )
            return [_row(row) for row in result.mappings().all()]

    async def decide(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        user_id: str,
        decision: str,
        reason: Optional[str],
        decided_by: str,
    ) -> Optional[Dict[str, Any]]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.runtime_approval_requests
                    SET status = :decision,
                        decision_reason = :reason,
                        decided_by = CAST(:decided_by AS uuid),
                        decided_at = now(),
                        request_payload = CASE
                            WHEN :decision = 'rejected' THEN '{}'::jsonb
                            ELSE request_payload
                        END,
                        updated_at = now()
                    WHERE approval_id = CAST(:approval_id AS uuid)
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                      AND status = 'pending'
                      AND expires_at > now()
                    RETURNING *
                    """
                ),
                {
                    "approval_id": approval_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "decision": decision,
                    "reason": reason,
                    "decided_by": decided_by,
                },
            )
            row = result.mappings().one_or_none()
            return _row(row) if row else None

    async def consume_approved(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        user_id: str,
        request_fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        """Atomically consume one approved receipt exactly once."""
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.runtime_approval_requests
                    SET status = 'consumed',
                        consumed_at = now(),
                        request_payload = '{}'::jsonb,
                        updated_at = now()
                    WHERE approval_id = CAST(:approval_id AS uuid)
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND user_id = CAST(:user_id AS uuid)
                      AND request_fingerprint = :request_fingerprint
                      AND status = 'approved'
                      AND expires_at > now()
                    RETURNING *
                    """
                ),
                {
                    "approval_id": approval_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "request_fingerprint": request_fingerprint,
                },
            )
            row = result.mappings().one_or_none()
            return _row(row) if row else None


_approval_repository: Optional[SqlApprovalRepository] = None


def get_approval_repository() -> SqlApprovalRepository:
    global _approval_repository
    if _approval_repository is None:
        _approval_repository = SqlApprovalRepository()
    return _approval_repository


__all__ = ["SqlApprovalRepository", "get_approval_repository"]
