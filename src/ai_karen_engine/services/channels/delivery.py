"""Host-owned, one-shot delivery through declared channel adapters.

Never infer delivery from ChatRuntime text or from an HTTP request being made.
Only native provider evidence can promote an accepted outbox record to sent.
Ambiguous calls become UNKNOWN and require provider reconciliation, never a
blind resend that could deliver duplicate messages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
)
from ai_karen_engine.extensions.channels.contracts import (
    ChannelAdapter,
    ChannelConnection,
    ChannelDeliveryReceipt,
    ChannelDeliveryState,
)
from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.persistence.repositories.channel_repository import (
    ClaimedChannelDelivery,
    SqlChannelRepository,
)
from ai_karen_engine.services.channels.execution import _stable_channel_session
from ai_karen_engine.persistence.repositories.channel_repository import ClaimedChannelMessage
from ai_karen_engine.services.automation.claim_lease import (
    ClaimLeaseLost,
    run_with_claim_heartbeat,
)

logger = logging.getLogger(__name__)


class ChannelDeliveryClaimLost(ClaimLeaseLost):
    """The provider may have been contacted but this worker lost ownership."""


class ChannelDeliveryDenied(PermissionError):
    """The host has not admitted the installed transport for outbound sending."""


class ChannelDeliveryService:
    """Transport dispatcher, not an AI-runtime or provider/model orchestrator."""

    def __init__(
        self, *, kernel: PluginKernel, repository: SqlChannelRepository,
    ) -> None:
        self._kernel = kernel
        self._repository = repository

    def _authorized_channel(self, connection: ChannelConnection) -> dict[str, Any]:
        registration = self._kernel.runtime_registry.get(connection.installation_id)
        if registration is None or registration.state is not ExtensionLifecycleState.ENABLED:
            raise ChannelDeliveryDenied("Transport extension is not enabled")
        capabilities = registration.manifest.capabilities
        if not any(c.id == "communication_channel" for c in capabilities):
            raise ChannelDeliveryDenied("Installed extension is not a channel")
        declared = registration.manifest.metadata.get("communication_channel")
        if not isinstance(declared, dict):
            raise ChannelDeliveryDenied("Channel contract metadata is unavailable")
        return declared

    @staticmethod
    async def _plan_allows(
        plan: AuthorizedExecutionPlan, *,
        tenant_id: str, user_id: str, installation_id: str,
        session_id: str,
    ) -> bool:
        """The provider adapter cannot mint or widen RuntimePolicy authority."""
        return bool(
            isinstance(plan, AuthorizedExecutionPlan)
            and plan.matches_execution_scope(
                tenant_id=tenant_id, user_id=user_id,
                session_id=session_id,
            )
            and installation_id in plan.allowed_plugins
            and not plan.approval_requirements
            and await ActionExecutionGate.authorize(plan, installation_id)
        )

    @staticmethod
    def _session_id(
        *, tenant_id: str, user_id: str, connection_id: str,
        external_conversation_id: str,
    ) -> str:
        """Reuse channel execution's canonical session derivation."""
        return _stable_channel_session(
            ClaimedChannelMessage(
                inbox_id="", correlation_id="", tenant_id=tenant_id,
                user_id=user_id, binding_id="", connection_id=connection_id,
                external_conversation_id=external_conversation_id,
                external_sender_id="", message_kind="text", text="",
            )
        )

    @staticmethod
    def _provider_receipt(
        *,
        claimed: ClaimedChannelDelivery,
        value: object,
        declared: dict[str, Any],
    ) -> ChannelDeliveryReceipt:
        """Downgrade unsupported/unproven states rather than making up success."""
        delivery_id = claimed.delivery.delivery_id
        unknown = ChannelDeliveryReceipt(
            delivery_id=delivery_id,
            state=ChannelDeliveryState.UNKNOWN,
            error_code="provider_receipt_unverified",
        )
        if not isinstance(value, ChannelDeliveryReceipt):
            return unknown
        if value.delivery_id != delivery_id:
            return unknown
        if value.state is ChannelDeliveryState.SENT:
            return value if value.provider_message_id else unknown
        if value.state in {ChannelDeliveryState.DELIVERED, ChannelDeliveryState.READ}:
            if (
                declared.get("supports_delivery_receipts") is True
                and value.provider_message_id
                and value.provider_receipt_id
            ):
                return value
            return unknown
        if value.state is ChannelDeliveryState.FAILED:
            return value if value.error_code else unknown
        if value.state is ChannelDeliveryState.UNKNOWN:
            return value
        # ACCEPTED means no confirmed provider delivery.
        return unknown

    async def dispatch(
        self, *, tenant_id: str, delivery_id: str,
        adapter: ChannelAdapter, authorized_plan: AuthorizedExecutionPlan,
        lease_seconds: int = 90,
    ) -> bool:
        """Attempt one host-authorized send; does not claim provider delivery."""
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("Outbound dispatch lease must be 3..3600 seconds")
        # Don't acquire a one-use reservation for a disabled transport.
        preflight = await self._repository.get_delivery_preflight(
            tenant_id=tenant_id, delivery_id=delivery_id,
        )
        if preflight is None:
            return False
        snapshot = await self._repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=preflight.connection_id,
        )
        if snapshot is None:
            raise ChannelDeliveryDenied("No enabled tenant channel connection")
        declared = self._authorized_channel(snapshot)
        if not await self._plan_allows(
            authorized_plan, tenant_id=tenant_id, user_id=preflight.user_id,
            installation_id=snapshot.installation_id,
            session_id=self._session_id(
                tenant_id=tenant_id, user_id=preflight.user_id,
                connection_id=preflight.connection_id,
                external_conversation_id=preflight.external_conversation_id,
            ),
        ):
            raise ChannelDeliveryDenied("Outbound action was not authorized by RuntimePolicy")
        claimed = await self._repository.claim_outbound(
            tenant_id=tenant_id, delivery_id=delivery_id, lease_seconds=lease_seconds,
        )
        if claimed is None:
            return False

        async def renew() -> bool:
            return await self._repository.renew_outbound_claim(
                tenant_id=tenant_id, delivery_id=delivery_id,
                claim_token=claimed.claim_token, lease_seconds=lease_seconds,
            )

        async def attempt() -> bool:
            # CORTEX/RuntimePolicy issue this plan. The transport never does.
            # Claim-bound user and tenant must exactly match its principal.
            if not await self._plan_allows(
                authorized_plan,
                tenant_id=claimed.connection.tenant_id,
                user_id=claimed.user_id,
                installation_id=claimed.connection.installation_id,
                session_id=self._session_id(
                    tenant_id=claimed.connection.tenant_id, user_id=claimed.user_id,
                    connection_id=claimed.connection.connection_id,
                    external_conversation_id=claimed.external_conversation_id,
                ),
            ):
                receipt = ChannelDeliveryReceipt(
                    delivery_id=delivery_id,
                    state=ChannelDeliveryState.FAILED,
                    error_code="outbound_policy_denied",
                )
                if not await self._repository.finalize_outbound_claim(
                    tenant_id=tenant_id, claim_token=claimed.claim_token,
                    receipt=receipt,
                ):
                    raise ChannelDeliveryClaimLost(
                        "Channel policy denial could not be persisted under claim"
                    )
                return False

            connection = await self._repository.get_enabled_connection(
                tenant_id=tenant_id, connection_id=claimed.connection.connection_id,
            )
            if (
                connection is None
                or connection.revision != claimed.connection.revision
                or connection.installation_id != claimed.connection.installation_id
            ):
                receipt = ChannelDeliveryReceipt(
                    delivery_id=delivery_id, state=ChannelDeliveryState.FAILED,
                    error_code="channel_connection_changed",
                )
            elif claimed.delivery.message_kind not in declared.get("outbound", []):
                receipt = ChannelDeliveryReceipt(
                    delivery_id=delivery_id, state=ChannelDeliveryState.FAILED,
                    error_code="outbound_kind_unsupported",
                )
            else:
                try:
                    value = await asyncio.wait_for(
                        adapter.send(connection=connection, delivery=claimed.delivery),
                        timeout=max(1.0, min(60.0, lease_seconds * 0.8)),
                    )
                except Exception as exc:
                    logger.warning(
                        "channel.delivery.provider_call_uncertain",
                        extra={
                            "tenant_id": tenant_id,
                            "delivery_id": delivery_id,
                            "connection_id": claimed.connection.connection_id,
                            "error_type": type(exc).__name__,
                        },
                    )
                    value = ChannelDeliveryReceipt(
                        delivery_id=delivery_id, state=ChannelDeliveryState.UNKNOWN,
                        error_code="provider_call_uncertain",
                    )
                receipt = self._provider_receipt(
                    claimed=claimed, value=value, declared=declared,
                )
            if not await self._repository.finalize_outbound_claim(
                tenant_id=tenant_id, claim_token=claimed.claim_token,
                receipt=receipt,
            ):
                raise ChannelDeliveryClaimLost(
                    "Channel provider outcome cannot be persisted by a stale claim"
                )
            logger.info(
                "channel.delivery.finalized",
                extra={
                    "tenant_id": tenant_id,
                    "delivery_id": delivery_id,
                    "connection_id": claimed.connection.connection_id,
                    "delivery_state": receipt.state.value,
                },
            )
            return receipt.state in {
                ChannelDeliveryState.SENT,
                ChannelDeliveryState.DELIVERED,
                ChannelDeliveryState.READ,
            }

        return await run_with_claim_heartbeat(
            attempt(), renew=renew,
            heartbeat_seconds=max(1.0, lease_seconds / 3.0),
            lost_error=ChannelDeliveryClaimLost,
            lost_message="Channel outbound lease lost during provider attempt",
        )


__all__ = [
    "ChannelDeliveryClaimLost",
    "ChannelDeliveryDenied",
    "ChannelDeliveryService",
]
