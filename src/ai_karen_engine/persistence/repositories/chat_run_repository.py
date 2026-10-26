"""Tenant- and owner-fenced persistence for in-flight ChatRuntime executions.

No messages or provider content live here. A CopilotKit transport runId is
untrusted correlation, never a globally authorized task identifier.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.config.runtime import get_runtime_settings

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


@dataclass(frozen=True)
class ChatRunLease:
    """Server-generated execution/lease identity scoped to one authenticated run."""

    execution_id: str
    lease_token: str
    tenant_id: str
    user_id: str
    conversation_id: str
    transport_run_id: str
    request_id: str
    correlation_id: str


def _uuid(value: str) -> str:
    return str(uuid.UUID(str(value)))


class SqlChatRunRepository:
    """Single PostgreSQL owner for durable chat-run admission and fencing.

    Every operation sets tenant and user PostgreSQL RLS context. The database
    mutation additionally matches both identities and the execution lease.
    """

    @staticmethod
    def _lease_seconds() -> int:
        return get_runtime_settings().timeouts.chat_run_lease_seconds

    async def admit(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        transport_run_id: str,
        request_id: str,
        correlation_id: str,
    ) -> Optional[ChatRunLease]:
        if not _RUN_ID_PATTERN.fullmatch(transport_run_id):
            raise ValueError("invalid_transport_run_id")
        if not request_id or not correlation_id:
            raise ValueError("missing_runtime_request_identity")
        tenant = _uuid(tenant_id)
        user = _uuid(user_id)
        conversation = _uuid(conversation_id)
        execution = str(uuid.uuid4())
        token = str(uuid.uuid4())
        async with async_transaction_scope(tenant, user_id=user) as session:
            # Only reconcile this authenticated user's expired leases. No
            # globally sweeping, unscoped mutation from a consumer request.
            await session.execute(
                text(
                    """
                    UPDATE public.runtime_chat_runs
                    SET status = 'orphaned', terminal_at = NOW(),
                        lease_token = NULL, lease_expires_at = NULL,
                        terminal_error_code = 'CHAT_RUN_LEASE_EXPIRED',
                        updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND status IN ('running', 'cancelling')
                      AND lease_expires_at <= NOW()
                    """
                ),
                {"tenant": tenant, "owner": user},
            )
            result = await session.execute(
                text(
                    """
                    INSERT INTO public.runtime_chat_runs (
                        execution_id, tenant_id, user_id, conversation_id,
                        transport_run_id, request_id, correlation_id,
                        status, lease_token, lease_expires_at
                    )
                    VALUES (
                        CAST(:execution AS uuid), CAST(:tenant AS uuid),
                        CAST(:owner AS uuid), CAST(:conversation AS uuid),
                        :run_id, :request_id, :correlation_id,
                        'running', CAST(:token AS uuid),
                        NOW() + make_interval(secs => :ttl)
                    )
                    ON CONFLICT (
                        tenant_id, user_id, conversation_id, transport_run_id
                    ) DO NOTHING
                    RETURNING execution_id
                    """
                ),
                {
                    "execution": execution,
                    "tenant": tenant,
                    "owner": user,
                    "conversation": conversation,
                    "run_id": transport_run_id,
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "token": token,
                    "ttl": self._lease_seconds(),
                },
            )
            if result.scalar_one_or_none() is None:
                return None
        return ChatRunLease(
            execution_id=execution,
            lease_token=token,
            tenant_id=tenant,
            user_id=user,
            conversation_id=conversation,
            transport_run_id=transport_run_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    async def renew(self, lease: ChatRunLease) -> bool:
        """CAS heartbeat: a lost/expired lease can never regain ownership."""
        async with async_transaction_scope(lease.tenant_id, user_id=lease.user_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.runtime_chat_runs
                    SET lease_expires_at = NOW() + make_interval(secs => :ttl),
                        updated_at = NOW()
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND lease_token = CAST(:token AS uuid)
                      AND lease_expires_at > NOW()
                      AND status = 'running'
                      AND cancel_requested_at IS NULL
                    RETURNING execution_id
                    """
                ),
                self._scope(lease, ttl=self._lease_seconds()),
            )
            return result.scalar_one_or_none() is not None

    async def finish(
        self,
        lease: ChatRunLease,
        *,
        status: str,
        error_code: Optional[str] = None,
    ) -> bool:
        """Exactly one fenced terminal transition, before signaling success."""
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid_chat_run_terminal_status")
        if error_code is not None and (
            len(error_code) > 64
            or re.fullmatch(r"[A-Z0-9_]+", error_code) is None
        ):
            raise ValueError("invalid_chat_run_error_code")
        async with async_transaction_scope(lease.tenant_id, user_id=lease.user_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.runtime_chat_runs
                    SET status = :status, terminal_at = NOW(), updated_at = NOW(),
                        terminal_error_code = :error_code,
                        lease_token = NULL, lease_expires_at = NULL
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND lease_token = CAST(:token AS uuid)
                      AND lease_expires_at > NOW()
                      AND status = 'running'
                      AND cancel_requested_at IS NULL
                    RETURNING execution_id
                    """
                ),
                self._scope(lease, status=status, error_code=error_code),
            )
            return result.scalar_one_or_none() is not None

    async def request_cancel(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        transport_run_id: str,
    ) -> Optional[str]:
        """Atomically request stop for ONE owned run; never cancel by thread alone.

        Row locking serializes stop with terminal transition. A repeated stop
        returns 'cancelling', not a second side effect. Terminal statuses are
        immutable. A missing or foreign run returns None without disclosure.
        """
        if not _RUN_ID_PATTERN.fullmatch(transport_run_id):
            raise ValueError("invalid_transport_run_id")
        scope = {
            "tenant": _uuid(tenant_id),
            "owner": _uuid(user_id),
            "conversation": _uuid(conversation_id),
            "run_id": transport_run_id,
        }
        async with async_transaction_scope(scope["tenant"], user_id=scope["owner"]) as session:
            locked = await session.execute(
                text(
                    """
                    SELECT status, lease_expires_at
                    FROM public.runtime_chat_runs
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND transport_run_id = :run_id
                    FOR UPDATE
                    """
                ),
                scope,
            )
            row = locked.mappings().one_or_none()
            if row is None:
                return None
            status = str(row["status"])
            if status != "running":
                return status
            # Lease expiry is checked inside the transaction: a dead worker is
            # not reported as successfully stopped.
            result = await session.execute(
                text(
                    """
                    UPDATE public.runtime_chat_runs
                    SET status = CASE
                            WHEN lease_expires_at > NOW() THEN 'cancelling'
                            ELSE 'orphaned'
                        END,
                        cancel_requested_at = CASE
                            WHEN lease_expires_at > NOW() THEN NOW()
                            ELSE NULL
                        END,
                        terminal_at = CASE
                            WHEN lease_expires_at > NOW() THEN NULL
                            ELSE NOW()
                        END,
                        terminal_error_code = CASE
                            WHEN lease_expires_at > NOW() THEN NULL
                            ELSE 'CHAT_RUN_LEASE_EXPIRED'
                        END,
                        lease_token = CASE
                            WHEN lease_expires_at > NOW() THEN lease_token
                            ELSE NULL
                        END,
                        updated_at = NOW()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND transport_run_id = :run_id
                      AND status = 'running'
                    RETURNING status
                    """
                ),
                scope,
            )
            next_status = result.scalar_one_or_none()
            if next_status is None:
                raise RuntimeError("chat_run_cancel_concurrent_state_changed")
            return str(next_status)

    async def cancel_requested(self, lease: ChatRunLease) -> bool:
        """Observe an authorized stop without accepting a caller's SDK token."""
        async with async_transaction_scope(lease.tenant_id, user_id=lease.user_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT status
                    FROM public.runtime_chat_runs
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND lease_token = CAST(:token AS uuid)
                      AND lease_expires_at > NOW()
                      AND status = 'cancelling'
                      AND cancel_requested_at IS NOT NULL
                    """
                ),
                self._scope(lease),
            )
            return result.scalar_one_or_none() == "cancelling"

    @staticmethod
    def _scope(lease: ChatRunLease, **extra: object) -> dict[str, object]:
        return {
            "execution": lease.execution_id,
            "tenant": lease.tenant_id,
            "owner": lease.user_id,
            "conversation": lease.conversation_id,
            "token": lease.lease_token,
            **extra,
        }
