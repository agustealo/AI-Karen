"""Authenticated channel event execution through the sole ChatRuntime authority.

Processing requires a durable inbox lease, current channel-account binding and
fresh principal authorization. The only outbound side effect is an atomic,
fenced publication into the channel outbox as ACCEPTED, never sent/delivered.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable

from ai_karen_engine.auth.auth_service import get_auth_service
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
)
from ai_karen_engine.extensions.channels.contracts import ChannelDeliveryRequest
from ai_karen_engine.persistence.repositories.channel_repository import (
    ClaimedChannelMessage,
    SqlChannelRepository,
)
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.auth.fresh_user_lookup import get_fresh_user_by_id
from ai_karen_engine.services.automation.claim_lease import (
    ClaimLeaseLost,
    run_with_claim_heartbeat,
)

logger = logging.getLogger(__name__)


class ChannelClaimLost(ClaimLeaseLost):
    """Processing cannot publish after a claim lease expires or is replaced."""


class ChannelExecutionDenied(PermissionError):
    """The linked principal or runtime response is not authorized for delivery."""


def _stable_channel_session(item: ClaimedChannelMessage) -> str:
    # This is distinct per tenant, linked principal and native conversation,
    # preventing cross-user transcript collisions in shared provider channels.
    pieces = (
        item.tenant_id, item.user_id, item.connection_id,
        item.external_conversation_id,
    )
    digest = hashlib.sha256("\x1f".join(pieces).encode("utf-8")).hexdigest()
    return f"channel-{digest}"


class ChannelExecutionService:
    """Bridge claimed channel messages into canonical ChatRuntime, never a new LLM path."""

    def __init__(
        self,
        *,
        repository: SqlChannelRepository,
        chat_runtime: ChatRuntime,
        principal_lookup: Callable[..., Awaitable[object]] | None = None,
    ) -> None:
        self._repository = repository
        self._chat_runtime = chat_runtime
        self._principal_lookup = principal_lookup or self._lookup_principal

    @staticmethod
    async def _lookup_principal(*, tenant_id: str, user_id: str) -> object:
        return await get_fresh_user_by_id(
            await get_auth_service(),
            user_id=user_id, tenant_id=tenant_id,
        )

    async def execute_claimed_text(
        self, *, tenant_id: str, inbox_id: str, claim_token: str,
        lease_seconds: int = 90,
    ) -> bool:
        """Execute a single leased event; no output without current ownership."""
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("Channel execution lease must be 3..3600 seconds")

        async def renew() -> bool:
            return await self._repository.renew_inbound_claim(
                tenant_id=tenant_id, inbox_id=inbox_id,
                claim_token=claim_token, lease_seconds=lease_seconds,
            )

        try:
            return await run_with_claim_heartbeat(
                self._process(
                    tenant_id=tenant_id, inbox_id=inbox_id, claim_token=claim_token,
                ),
                renew=renew,
                heartbeat_seconds=max(1.0, lease_seconds / 3.0),
                lost_error=ChannelClaimLost,
                lost_message="Channel claim was lost before completion",
            )
        except ChannelClaimLost:
            raise
        except Exception as exc:
            logger.warning(
                "channel.execution.failed",
                extra={
                    "tenant_id": tenant_id,
                    "inbox_id": inbox_id,
                    "error_type": type(exc).__name__,
                },
            )
            success = await self._repository.fail_inbound_claim(
                tenant_id=tenant_id, inbox_id=inbox_id,
                claim_token=claim_token, error_code="channel_execution_failed",
            )
            if not success:
                raise ChannelClaimLost("Channel claim was lost during failure") from exc
            raise

    async def _process(
        self, *, tenant_id: str, inbox_id: str, claim_token: str,
    ) -> bool:
        item = await self._repository.load_claimed_message(
            tenant_id=tenant_id, inbox_id=inbox_id, claim_token=claim_token,
        )
        if item is None:
            raise ChannelClaimLost("No active channel claim or sender binding")
        principal = await self._principal_lookup(
            tenant_id=item.tenant_id, user_id=item.user_id,
        )
        if (
            principal is None
            or getattr(principal, "status", None) != UserStatus.ACTIVE
            or str(getattr(principal, "tenant_id", "") or "") != item.tenant_id
            or str(getattr(principal, "id", "") or "") != item.user_id
        ):
            raise ChannelExecutionDenied("Channel principal is no longer authorized")

        roles = [
            str(getattr(role, "value", role))
            for role in (getattr(principal, "roles", None) or ())
        ]
        session_id = _stable_channel_session(item)
        request = ChatExecutionRequest(
            messages=[{"role": "user", "content": item.text}],
            context=ChatExecutionContext(
                user_id=item.user_id,
                tenant_id=item.tenant_id,
                session_id=session_id,
                request_id=item.inbox_id,
                correlation_id=item.correlation_id,
                roles=roles,
                permissions=[],
            ),
            metadata={
                "transport": "communication_channel",
                "channel_connection_id": item.connection_id,
                "channel_inbox_id": item.inbox_id,
            },
        )
        result = await self._chat_runtime.execute(request)
        response_meta = result.metadata.to_dict()
        if (
            result.status is not ChatExecutionStatus.OK
            or not result.answer.strip()
            or response_meta.get("degraded_mode") is True
            or response_meta.get("response_source") not in {
                "model", "tool", "plugin", "agent", "workflow"
            }
        ):
            raise ChannelExecutionDenied(
                "ChatRuntime did not produce a deliverable verified response"
            )
        delivery = ChannelDeliveryRequest(
            delivery_id=str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"karen-channel-delivery:{item.inbox_id}")
            ),
            connection_id=item.connection_id,
            destination_id=item.external_conversation_id,
            idempotency_key=item.inbox_id,
            message_kind="text",
            text=result.answer,
        )
        committed = await self._repository.complete_and_stage_delivery(
            tenant_id=item.tenant_id, inbox_id=item.inbox_id,
            claim_token=claim_token, delivery=delivery,
        )
        if not committed:
            raise ChannelClaimLost("Channel reply could not be committed under lease")
        logger.info(
            "channel.execution.outbox_accepted",
            extra={
                "tenant_id": item.tenant_id,
                "user_id": item.user_id,
                "correlation_id": item.correlation_id,
                "inbox_id": item.inbox_id,
                "connection_id": item.connection_id,
            },
        )
        return True


__all__ = [
    "ChannelClaimLost",
    "ChannelExecutionDenied",
    "ChannelExecutionService",
]
