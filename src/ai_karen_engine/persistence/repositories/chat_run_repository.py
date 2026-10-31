"""Tenant- and owner-fenced persistence for in-flight ChatRuntime executions.

No messages or provider content live here. A CopilotKit transport runId is
untrusted correlation, never a globally authorized task identifier.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.config.runtime import get_runtime_settings

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_EVENT_TYPES = frozenset({
    "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT",
    "TEXT_MESSAGE_END", "ACTIVITY_SNAPSHOT", "TOOL_CALL_START",
    "TOOL_CALL_END", "SUBAGENT_STARTED", "SUBAGENT_FINISHED",
    "SUBAGENT_ERROR", "CUSTOM", "RUN_ERROR", "RUN_FINISHED",
})
_MAX_EVENT_BYTES = 32768
_MAX_EVENTS_PER_RUN = 2048
_MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_MAX_EVENT_READ = 100


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
        # A successful durable run can only be written by the canonical
        # conversation repository IN THE SAME transaction as both messages.
        if status == "completed":
            raise ValueError("chat_run_completion_requires_atomic_transcript_commit")
        if status not in {"failed", "cancelled"}:
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
                      AND (
                          (:status = 'cancelled' AND status IN ('running', 'cancelling'))
                          OR (:status != 'cancelled' AND status = 'running'
                              AND cancel_requested_at IS NULL)
                      )
                    RETURNING execution_id
                    """
                ),
                self._scope(lease, status=status, error_code=error_code),
            )
            return result.scalar_one_or_none() is not None

    async def committed_turn(
        self,
        lease: ChatRunLease,
        *,
        user_message_id: str,
        assistant_message_id: str,
    ) -> bool:
        """Read-only proof that the completed run and BOTH messages committed.

        A terminal receipt is not inferred from a model COMPLETE chunk. The
        repository must have atomically committed the scoped run and the two
        idempotent canonical transcript messages.
        """
        try:
            user_message = _uuid(user_message_id)
            assistant_message = _uuid(assistant_message_id)
        except (TypeError, ValueError, AttributeError):
            return False
        async with async_transaction_scope(
            lease.tenant_id, user_id=lease.user_id,
        ) as session:
            result = await session.execute(
                text("""
                    SELECT 1
                    FROM public.runtime_chat_runs r
                    JOIN conversations c
                      ON c.conversation_id = r.conversation_id
                     AND c.tenant_id = r.tenant_id
                     AND c.user_id = r.user_id
                    JOIN messages u
                      ON u.conversation_id = c.conversation_id
                     AND u.message_id::text = :user_message
                     AND u.role = 'user'
                    JOIN messages a
                      ON a.conversation_id = c.conversation_id
                     AND a.message_id::text = :assistant_message
                     AND a.role = 'assistant'
                    WHERE r.execution_id = CAST(:execution AS uuid)
                      AND r.tenant_id = CAST(:tenant AS uuid)
                      AND r.user_id = CAST(:owner AS uuid)
                      AND r.conversation_id = CAST(:conversation AS uuid)
                      AND r.transport_run_id = :transport_run_id
                      AND r.request_id = :request_id
                      AND r.correlation_id = :correlation_id
                      AND r.status = 'completed'
                      AND r.terminal_at IS NOT NULL
                      AND r.user_message_id = CAST(:user_message AS uuid)
                      AND r.assistant_message_id = CAST(:assistant_message AS uuid)
                      AND r.assistant_message_digest IS NOT NULL
                      AND u.message_metadata::jsonb ->> 'request_id' = r.request_id
                      AND a.message_metadata::jsonb ->> 'request_id' = r.request_id
                    LIMIT 1
                """),
                {
                    **self._scope(lease),
                    "transport_run_id": lease.transport_run_id,
                    "request_id": lease.request_id,
                    "correlation_id": lease.correlation_id,
                    "user_message": user_message,
                    "assistant_message": assistant_message,
                },
            )
            return result.scalar_one_or_none() is not None

    async def append_projected_event(
        self, lease: ChatRunLease, *, event: Mapping[str, Any],
    ) -> int:
        """Append one actual AG-UI projection under fenced, scoped SQL row lock.

        No provider payload is accepted, and no event can authorize inference,
        tools, actions or an invented completion. Every sequence number is
        serialized by locking its parent run, including terminal writers.
        """
        event_type = event.get("type") if isinstance(event, Mapping) else None
        if not isinstance(event_type, str) or event_type not in _EVENT_TYPES:
            raise ValueError("invalid_chat_projection_event")
        if not isinstance(event, dict):
            event = dict(event)
        if event_type in {"RUN_STARTED", "RUN_FINISHED"} and (
            event.get("threadId") != lease.conversation_id
            or event.get("runId") != lease.transport_run_id
        ):
            raise ValueError("chat_projection_identity_mismatch")
        if event_type == "CUSTOM" and (
            not isinstance(event.get("name"), str)
            or event.get("name") not in {
            "karen.presentation.v1", "karen.execution_receipt.v1",
            "karen.response_integrity.v1", "karen.citations",
            "karen.agent_step", "karen.tool_activity", "karen.learning_decision",
            "karen.approval_required", "karen.status", "karen.warning",
            "karen.checkpoint",
            }
        ):
            raise ValueError("unsupported_chat_projection_custom_event")
        try:
            encoded = json.dumps(
                event, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("unserializable_chat_projection_event") from exc
        if len(encoded.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise ValueError("chat_projection_event_size_limit")

        async with async_transaction_scope(
            lease.tenant_id, user_id=lease.user_id,
        ) as session:
            locked = await session.execute(
                text("""
                    SELECT status, lease_token, lease_expires_at,
                           cancel_requested_at, terminal_at,
                           assistant_message_id, assistant_message_digest
                    FROM public.runtime_chat_runs
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND transport_run_id = :run_id
                      AND request_id = :request_id
                      AND correlation_id = :correlation_id
                    FOR UPDATE
                """),
                {
                    **self._scope(lease),
                    "run_id": lease.transport_run_id,
                    "request_id": lease.request_id,
                    "correlation_id": lease.correlation_id,
                },
            )
            row = locked.mappings().one_or_none()
            if row is None:
                raise ValueError("chat_projection_run_unavailable")
            status = str(row["status"])
            if event_type == "RUN_FINISHED":
                allowed = (
                    status == "completed"
                    and row["terminal_at"] is not None
                    and row["assistant_message_id"] is not None
                    and isinstance(row["assistant_message_digest"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", row["assistant_message_digest"])
                    is not None
                )
            elif event_type == "RUN_ERROR":
                allowed = (
                    status in {"failed", "cancelled", "orphaned"}
                    and row["terminal_at"] is not None
                )
            elif status == "completed" and (
                event_type == "TEXT_MESSAGE_END"
                or (
                    event_type == "CUSTOM"
                    and event.get("name") in {
                        "karen.execution_receipt.v1",
                        "karen.response_integrity.v1",
                    }
                )
            ):
                # Canonical COMPLETE projects message-end and bounded
                # receipts BEFORE RUN_FINISHED, after the atomic transcript
                # transaction has already committed. Allow exactly those
                # observed final-envelope events, not fresh model tokens.
                allowed = (
                    row["terminal_at"] is not None
                    and row["assistant_message_id"] is not None
                    and isinstance(row["assistant_message_digest"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", row["assistant_message_digest"])
                    is not None
                )
            else:
                allowed = (
                    status == "running"
                    and str(row["lease_token"]) == lease.lease_token
                    and row["cancel_requested_at"] is None
                    and row["lease_expires_at"] is not None
                )
                if allowed:
                    fresh = await session.execute(
                        text("""
                            SELECT 1
                            FROM public.runtime_chat_runs
                            WHERE execution_id = CAST(:execution AS uuid)
                              AND tenant_id = CAST(:tenant AS uuid)
                              AND user_id = CAST(:owner AS uuid)
                              AND conversation_id = CAST(:conversation AS uuid)
                              AND lease_token = CAST(:token AS uuid)
                              AND lease_expires_at > clock_timestamp()
                              AND status = 'running'
                              AND cancel_requested_at IS NULL
                        """),
                        self._scope(lease),
                    )
                    allowed = fresh.scalar_one_or_none() is not None
            if not allowed:
                raise ValueError("chat_projection_run_not_active")
            aggregate = await session.execute(
                text("""
                    SELECT COALESCE(MAX(event_seq), 0) AS last_seq,
                           COALESCE(SUM(octet_length(event_payload::text)), 0) AS bytes
                    FROM public.runtime_chat_run_events
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                """),
                self._scope(lease),
            )
            counter = aggregate.mappings().one()
            seq = int(counter["last_seq"]) + 1
            if seq > _MAX_EVENTS_PER_RUN or int(counter["bytes"]) + len(
                encoded.encode("utf-8")
            ) > _MAX_JOURNAL_BYTES:
                raise ValueError("chat_projection_journal_limit")
            # Terminal events are distinct from the durable status; a retry
            # cannot duplicate an observed completion/error in the journal.
            if event_type in {"RUN_FINISHED", "RUN_ERROR"}:
                prior = await session.execute(
                    text("""
                        SELECT 1 FROM public.runtime_chat_run_events
                        WHERE execution_id = CAST(:execution AS uuid)
                          AND tenant_id = CAST(:tenant AS uuid)
                          AND user_id = CAST(:owner AS uuid)
                          AND conversation_id = CAST(:conversation AS uuid)
                          AND event_type IN ('RUN_FINISHED', 'RUN_ERROR')
                        LIMIT 1
                    """),
                    self._scope(lease),
                )
                if prior.scalar_one_or_none() is not None:
                    raise ValueError("chat_projection_terminal_already_recorded")
            written = await session.execute(
                text("""
                    INSERT INTO public.runtime_chat_run_events (
                        execution_id, tenant_id, user_id, conversation_id,
                        event_seq, event_type, event_payload
                    ) VALUES (
                        CAST(:execution AS uuid), CAST(:tenant AS uuid),
                        CAST(:owner AS uuid), CAST(:conversation AS uuid),
                        :seq, :event_type, CAST(:event_payload AS jsonb)
                    ) RETURNING event_seq
                """),
                self._scope(
                    lease, seq=seq, event_type=event_type, event_payload=encoded,
                ),
            )
            saved_seq = written.scalar_one_or_none()
            if saved_seq != seq:
                raise RuntimeError("chat_projection_journal_commit_unverified")
        return seq

    async def read_projected_events(
        self, *, tenant_id: str, user_id: str, conversation_id: str,
        transport_run_id: str, after: int = 0, limit: int = 50,
    ) -> Optional[dict[str, Any]]:
        """Return observed events only; recovery never runs inference.

        An expired in-flight run is reported as interrupted. A committed
        transcript is NOT converted into a synthetic journal terminal.
        """
        if not _RUN_ID_PATTERN.fullmatch(transport_run_id):
            raise ValueError("invalid_transport_run_id")
        if type(after) is not int or not 0 <= after <= _MAX_EVENTS_PER_RUN:
            raise ValueError("invalid_chat_event_cursor")
        if type(limit) is not int or not 1 <= limit <= _MAX_EVENT_READ:
            raise ValueError("invalid_chat_event_page_limit")
        scope = {
            "tenant": _uuid(tenant_id), "owner": _uuid(user_id),
            "conversation": _uuid(conversation_id),
            "run_id": transport_run_id, "after": after, "limit": limit + 1,
        }
        async with async_transaction_scope(
            scope["tenant"], user_id=scope["owner"],
        ) as session:
            # SHARE lock gives state and events one coherent snapshot while
            # serializing against the append and terminal-row write.
            result = await session.execute(
                text("""
                    SELECT execution_id, status, lease_expires_at, terminal_at
                    FROM public.runtime_chat_runs
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND transport_run_id = :run_id
                    FOR SHARE
                """),
                scope,
            )
            run = result.mappings().one_or_none()
            if run is None:
                return None
            events = await session.execute(
                text("""
                    SELECT event_seq, event_payload
                    FROM public.runtime_chat_run_events
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND event_seq > :after
                    ORDER BY event_seq ASC
                    LIMIT :limit
                """),
                {**scope, "execution": str(run["execution_id"])},
            )
            records = events.mappings().all()
            observed_terminal = await session.execute(
                text("""
                    SELECT event_type FROM public.runtime_chat_run_events
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND event_type IN ('RUN_FINISHED', 'RUN_ERROR')
                    LIMIT 1
                """),
                {**scope, "execution": str(run["execution_id"])},
            )
            journal_terminal_type = observed_terminal.scalar_one_or_none()
            journal_terminal_seen = journal_terminal_type is not None
            if journal_terminal_type is not None and (
                (
                    str(run["status"]) == "completed"
                    and journal_terminal_type != "RUN_FINISHED"
                )
                or (
                    str(run["status"]) in {"failed", "cancelled", "orphaned"}
                    and journal_terminal_type != "RUN_ERROR"
                )
                or str(run["status"]) in {"running", "cancelling"}
            ):
                raise RuntimeError("chat_run_journal_terminal_state_mismatch")
            # Snapshot-local DB clock, not a client-supplied time estimate.
            if run["status"] in {"running", "cancelling"}:
                fresh = await session.execute(
                    text("""
                        SELECT 1 FROM public.runtime_chat_runs
                        WHERE execution_id = CAST(:execution AS uuid)
                          AND lease_expires_at > clock_timestamp()
                    """),
                    {"execution": str(run["execution_id"])},
                )
                alive = fresh.scalar_one_or_none() is not None
            else:
                alive = False
        more = len(records) > limit
        page = records[:limit]
        state = str(run["status"])
        if state in {"running", "cancelling"} and not alive:
            state = "interrupted"
        return {
            "threadId": scope["conversation"],
            "runId": transport_run_id,
            "owner_user_id": scope["owner"],
            "owner_tenant_id": scope["tenant"],
            "events": [
                {"seq": int(rec["event_seq"]), "event": (
                    json.loads(rec["event_payload"])
                    if isinstance(rec["event_payload"], str)
                    else rec["event_payload"]
                )}
                for rec in page
            ],
            "nextCursor": int(page[-1]["event_seq"]) if page else after,
            "hasMore": more,
            "runStatus": state,
            "terminalConfirmed": state in {
                "completed", "failed", "cancelled", "orphaned",
            },
            "journalTerminalObserved": journal_terminal_seen,
            "continuationAvailable": False,
            "responseSource": "observed_event_journal",
        }

    async def completed_agent_activity(
        self, *, tenant_id: str, user_id: str, conversation_id: str,
    ) -> dict[str, tuple[str, str, str, list[dict[str, Any]]]]:
        """Owner-scoped, finalized journal steps correlated to saved messages.

        No inference occurs here. Only completed runs with a committed assistant
        message and an observed successful journal terminal can contribute.
        """
        scope = {
            "tenant": _uuid(tenant_id), "owner": _uuid(user_id),
            "conversation": _uuid(conversation_id),
        }
        async with async_transaction_scope(scope["tenant"], user_id=scope["owner"]) as session:
            result = await session.execute(text("""
                SELECT r.assistant_message_id::text AS message_id,
                       r.request_id, r.assistant_message_digest,
                       r.transport_run_id, e.event_seq, e.event_type,
                       e.event_payload
                FROM public.runtime_chat_runs r
                JOIN conversations c ON c.conversation_id = r.conversation_id
                  AND c.tenant_id = r.tenant_id AND c.user_id = r.user_id
                JOIN messages a ON a.conversation_id = c.conversation_id
                  AND a.message_id::text = r.assistant_message_id::text
                  AND a.role = 'assistant'
                JOIN messages u ON u.conversation_id = c.conversation_id
                  AND u.message_id::text = r.user_message_id::text
                  AND u.role = 'user'
                JOIN public.runtime_chat_run_events e
                  ON e.execution_id = r.execution_id
                  AND e.tenant_id = r.tenant_id AND e.user_id = r.user_id
                  AND e.conversation_id = r.conversation_id
                  AND (e.event_type = 'RUN_FINISHED'
                    OR (e.event_type = 'CUSTOM'
                      AND e.event_payload ->> 'name' = 'karen.agent_step'))
                WHERE r.tenant_id = CAST(:tenant AS uuid)
                  AND r.user_id = CAST(:owner AS uuid)
                  AND r.conversation_id = CAST(:conversation AS uuid)
                  AND r.status = 'completed' AND r.terminal_at IS NOT NULL
                  AND r.user_message_id IS NOT NULL
                  AND r.assistant_message_id IS NOT NULL
                  AND a.message_metadata::jsonb ->> 'request_id' = r.request_id
                  AND u.message_metadata::jsonb ->> 'request_id' = r.request_id
                ORDER BY r.created_at, r.execution_id, e.event_seq
                LIMIT 50001
            """), scope)
            rows = result.mappings().all()
        if len(rows) > 50000:
            raise RuntimeError("chat_activity_replay_limit_exceeded")
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            message_id = str(row["message_id"])
            saved = grouped.get(message_id)
            if saved is None:
                if len(grouped) >= 500:
                    raise RuntimeError("chat_activity_message_limit_exceeded")
                digest = str(row["assistant_message_digest"])
                if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    raise RuntimeError("chat_activity_invalid_digest")
                saved = {
                    "request_id": str(row["request_id"]), "digest": digest,
                    "run_id": str(row["transport_run_id"]), "terminal": False,
                    "events": [],
                }
                grouped[message_id] = saved
            if (saved["request_id"] != str(row["request_id"])
                    or saved["digest"] != str(row["assistant_message_digest"])
                    or saved["run_id"] != str(row["transport_run_id"])):
                raise RuntimeError("chat_activity_multiple_run_owners")
            event = row["event_payload"]
            if isinstance(event, str):
                event = json.loads(event)
            if not isinstance(event, dict):
                raise RuntimeError("chat_activity_invalid_journal_payload")
            if row["event_type"] == "RUN_FINISHED":
                if (saved["terminal"] or event.get("type") != "RUN_FINISHED"
                        or event.get("runId") != saved["run_id"]
                        or event.get("threadId") != scope["conversation"]):
                    raise RuntimeError("chat_activity_terminal_mismatch")
                saved["terminal"] = True
            else:
                if saved["terminal"]:
                    raise RuntimeError("chat_activity_post_terminal_event")
                saved["events"].append({
                    "seq": int(row["event_seq"]), "event": event,
                })
                if len(saved["events"]) > 100:
                    raise RuntimeError("chat_activity_step_limit_exceeded")
        if any(not saved["terminal"] and saved["events"] for saved in grouped.values()):
            raise RuntimeError("chat_activity_journal_incomplete")
        return {
            message_id: (
                saved["request_id"], saved["digest"],
                saved["run_id"], saved["events"],
            )
            for message_id, saved in grouped.items()
            if saved["terminal"] and saved["events"]
        }

    async def completed_replay_attestations(
        self, *, tenant_id: str, user_id: str, conversation_id: str,
    ) -> dict[str, tuple[str, str]]:
        """Read message ID to (request ID, saved digest) under owner RLS.

        The result maps only exact assistant message UUIDs to the request ID
        whose transcript and completion committed in the same transaction.
        No message payload, hidden tool content, or SDK state is returned.
        """
        scope = {
            "tenant": _uuid(tenant_id),
            "owner": _uuid(user_id),
            "conversation": _uuid(conversation_id),
        }
        async with async_transaction_scope(
            scope["tenant"], user_id=scope["owner"],
        ) as session:
            result = await session.execute(
                text("""
                    SELECT r.assistant_message_id::text AS message_id,
                           r.request_id, r.assistant_message_digest
                    FROM public.runtime_chat_runs r
                    JOIN conversations c
                      ON c.conversation_id = r.conversation_id
                     AND c.tenant_id = r.tenant_id
                     AND c.user_id = r.user_id
                    JOIN messages a
                      ON a.conversation_id = c.conversation_id
                     AND a.message_id::text = r.assistant_message_id::text
                     AND a.role = 'assistant'
                    JOIN messages u
                      ON u.conversation_id = c.conversation_id
                     AND u.message_id::text = r.user_message_id::text
                     AND u.role = 'user'
                    WHERE r.tenant_id = CAST(:tenant AS uuid)
                      AND r.user_id = CAST(:owner AS uuid)
                      AND r.conversation_id = CAST(:conversation AS uuid)
                      AND r.status = 'completed'
                      AND r.terminal_at IS NOT NULL
                      AND r.user_message_id IS NOT NULL
                      AND r.assistant_message_id IS NOT NULL
                      AND r.assistant_message_digest ~ '^[0-9a-f]{64}$'
                      AND a.message_metadata::jsonb ->> 'request_id' = r.request_id
                      AND u.message_metadata::jsonb ->> 'request_id' = r.request_id
                    ORDER BY r.created_at, r.execution_id
                    LIMIT 501
                """),
                scope,
            )
            rows = result.mappings().all()
            if len(rows) > 500:
                raise RuntimeError("chat_replay_attestation_limit_exceeded")
            return {
                str(row["message_id"]): (
                    str(row["request_id"]),
                    str(row["assistant_message_digest"]),
                )
                for row in rows
            }

    async def completed(self, lease: ChatRunLease) -> bool:
        """Check terminal status while upstream finishes post-commit telemetry."""
        async with async_transaction_scope(
            lease.tenant_id, user_id=lease.user_id,
        ) as session:
            result = await session.execute(
                text("""
                    SELECT 1
                    FROM public.runtime_chat_runs
                    WHERE execution_id = CAST(:execution AS uuid)
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND transport_run_id = :transport_run_id
                      AND request_id = :request_id
                      AND correlation_id = :correlation_id
                      AND status = 'completed'
                      AND terminal_at IS NOT NULL
                """),
                {
                    **self._scope(lease),
                    "transport_run_id": lease.transport_run_id,
                    "request_id": lease.request_id,
                    "correlation_id": lease.correlation_id,
                },
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
            if status not in {"running", "cancelling"}:
                return status
            # Repeated stops on an expired cancelling worker must not lie.
            # Lease expiry is checked inside the same transaction.
            result = await session.execute(
                text(
                    """
                    UPDATE public.runtime_chat_runs
                    SET status = CASE
                            WHEN lease_expires_at > NOW() THEN 'cancelling'
                            ELSE 'orphaned'
                        END,
                        cancel_requested_at = CASE
                            WHEN lease_expires_at > NOW()
                                THEN COALESCE(cancel_requested_at, NOW())
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
                      AND status IN ('running', 'cancelling')
                    RETURNING status
                    """
                ),
                scope,
            )
            next_status = result.scalar_one_or_none()
            if next_status is None:
                raise RuntimeError("chat_run_cancel_concurrent_state_changed")
            return str(next_status)

    async def read_status(
        self, *, tenant_id: str, user_id: str, conversation_id: str,
        transport_run_id: str,
    ) -> Optional[dict[str, Any]]:
        """Read one tenant/owner-scoped durable outcome, without mutation.

        A transport run ID is correlation only, never a bearer authorization.
        This works even when the optional AG-UI event journal is disabled.
        """
        if not _RUN_ID_PATTERN.fullmatch(transport_run_id):
            raise ValueError("invalid_transport_run_id")
        scope = {
            "tenant": _uuid(tenant_id),
            "owner": _uuid(user_id),
            "conversation": _uuid(conversation_id),
            "run_id": transport_run_id,
        }
        async with async_transaction_scope(
            scope["tenant"], user_id=scope["owner"],
        ) as session:
            result = await session.execute(
                text("""
                    SELECT status,
                           cancel_requested_at IS NOT NULL AS stop_requested,
                           terminal_at IS NOT NULL AS terminal_recorded,
                           lease_expires_at > clock_timestamp() AS lease_live
                    FROM public.runtime_chat_runs
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND user_id = CAST(:owner AS uuid)
                      AND conversation_id = CAST(:conversation AS uuid)
                      AND transport_run_id = :run_id
                    LIMIT 1
                """),
                scope,
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        status = str(row["status"])
        if status not in {
            "running", "cancelling", "cancelled", "completed",
            "failed", "orphaned",
        }:
            raise RuntimeError("unrecognized_chat_run_status")
        requested = row["stop_requested"] is True
        terminal = row["terminal_recorded"] is True
        if status in {"completed", "cancelled", "failed", "orphaned"} and not terminal:
            raise RuntimeError("unverified_chat_run_terminal")
        if status in {"running", "cancelling"} and row["lease_live"] is not True:
            status = "interrupted"
        return {
            "status": status,
            "cancel_requested": requested,
            "cancellation_confirmed": (
                status == "cancelled" and requested and terminal
            ),
        }

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
