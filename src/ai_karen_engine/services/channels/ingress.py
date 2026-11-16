"""Host-owned authenticated transport ingress for communication extensions.

This stage performs verified protocol admission into a durable, tenant-RLS inbox.
It deliberately does NOT claim to process or deliver a chat turn. Subsequent
gateway stages own fresh principal validation, ChatRuntime execution and outbox.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Mapping

from ai_karen_engine.extensions.channels.contracts import (
    ChannelAdapter,
    ChannelConnection,
    ChannelProviderStatusEvent,
    ChannelWebhookBatch,
    InboundChannelEvent,
    VerifiedIdentityBinding,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelAdmissionDenied,
    InboundAdmission,
    SqlChannelRepository,
)

logger = logging.getLogger(__name__)


class ChannelNativeBodyTooLarge(ValueError):
    """Verified installation envelope exceeds its declared transport budget."""



class ChannelIngressService:
    """Resolve installed transport authority, verify native data, admit once."""

    def __init__(
        self,
        *,
        kernel: PluginKernel,
        repository: SqlChannelRepository,
        max_native_body_bytes: int,
        on_admitted: Callable[[InboundAdmission], Awaitable[bool]] | None = None,
    ) -> None:
        if not 1 <= max_native_body_bytes <= 10_485_760:
            raise ValueError("Invalid channel request body budget")
        self._kernel = kernel
        self._repository = repository
        self._max_native_body_bytes = max_native_body_bytes
        self._on_admitted = on_admitted

    async def _verify_native_event(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        adapter: ChannelAdapter,
        headers: Mapping[str, str],
        body: bytes,
        allow_batch: bool = False,
    ) -> tuple[ChannelConnection, InboundChannelEvent | ChannelWebhookBatch]:
        """Authenticate native bytes once, then normalize through the canonical adapter."""
        if not tenant_id or not connection_id:
            raise ChannelAdmissionDenied("Host tenant and connection are required")
        if not isinstance(body, bytes):
            raise ValueError("Native channel body must be bytes")
        if len(body) > self._max_native_body_bytes:
            raise ChannelNativeBodyTooLarge("Native channel body exceeds configured budget")

        # Tenant scope is host-provided; do not trust tenant/user claims in body.
        connection = await self._repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if connection is None or connection.tenant_id != tenant_id:
            raise ChannelAdmissionDenied("Channel connection is inactive or outside tenant")

        catalog = self._kernel.get_channel_activation_manifest(
            connection.installation_id
        )
        if catalog is None:
            raise ChannelAdmissionDenied("Installed channel is not available to the host")
        channel_capability = catalog.capabilities.communication_channel
        if channel_capability is None:
            raise ChannelAdmissionDenied("Installed extension is not a channel")
        declared_budget = getattr(
            channel_capability, "max_native_body_bytes", self._max_native_body_bytes,
        )
        if type(declared_budget) is not int or not 1 <= declared_budget <= 10_485_760:
            raise ChannelAdmissionDenied("Invalid installed channel body budget")
        if len(body) > declared_budget:
            raise ChannelNativeBodyTooLarge("Native channel body exceeds transport budget")
        if not self._kernel.is_canonical_channel_adapter(
            connection.installation_id, adapter
        ):
            raise ChannelAdmissionDenied("Channel adapter does not match installed host code")

        # An approved adapter is injected by the host's plugin lifecycle; no
        # transport-specific route imports or alternate extension registry.
        try:
            verified = await adapter.verify_event(
                connection=connection, headers=headers, body=body,
            )
        except Exception as exc:
            logger.warning(
                "channel.ingress.verification_failed",
                extra={"error_type": type(exc).__name__,
                       "connection_id": connection_id},
            )
            raise ChannelAdmissionDenied("Native channel verification failed") from None
        if verified is not True:
            raise ChannelAdmissionDenied("Native channel verification failed")

        try:
            batch_normalizer = getattr(adapter, "normalize_events", None) if allow_batch else None
            if callable(batch_normalizer):
                event = await batch_normalizer(
                    connection=connection, headers=headers, body=body,
                )
            else:
                event = await adapter.normalize_event(
                    connection=connection, headers=headers, body=body,
                )
        except Exception as exc:
            logger.warning(
                "channel.ingress.normalization_failed",
                extra={"error_type": type(exc).__name__,
                       "connection_id": connection_id},
            )
            raise ChannelAdmissionDenied("Native channel normalization failed") from None
        if not isinstance(event, (InboundChannelEvent, ChannelWebhookBatch)):
            raise ChannelAdmissionDenied("Adapter returned invalid event contract")
        native_messages = event.messages if isinstance(event, ChannelWebhookBatch) else (event,)
        for message in native_messages:
            if message.connection_id != connection.connection_id:
                raise ChannelAdmissionDenied("Adapter event connection mismatch")
            if message.message_kind not in channel_capability.inbound:
                raise ChannelAdmissionDenied("Unsupported inbound channel message kind")
        if isinstance(event, ChannelWebhookBatch):
            for status in event.statuses:
                if status.connection_id != connection.connection_id:
                    raise ChannelAdmissionDenied("Provider status connection mismatch")
        return connection, event

    @property
    def max_native_body_bytes(self) -> int:
        return self._max_native_body_bytes

    @staticmethod
    def _is_link_command(event: InboundChannelEvent) -> bool:
        # This command prefix is reserved; even malformed link secrets never
        # become ChatRuntime messages, memories, or plugin parameters.
        return (
            event.message_kind == "text"
            and isinstance(event.text, str)
            and re.match(
                r"^\s*/link(?:@[A-Za-z0-9_]{1,32})?(?:\s|$)",
                event.text,
                flags=re.IGNORECASE,
            ) is not None
        )

    async def _admit_event(
        self, *, connection: ChannelConnection, event: InboundChannelEvent,
    ) -> InboundAdmission:
        if self._is_link_command(event):
            raise ChannelAdmissionDenied("Link proofs use identity admission only")
        admission = await self._repository.admit_verified_inbound(
            connection=connection, event=event,
        )
        if self._on_admitted is not None:
            try:
                scheduled = await self._on_admitted(admission)
                if scheduled is not True:
                    logger.warning(
                        "channel.ingress.worker_deferred",
                        extra={"tenant_id": admission.tenant_id,
                               "inbox_id": admission.inbox_id},
                    )
            except Exception as exc:
                # Inbox is committed. Never turn valid ingress into an HTTP
                # retry storm when the process-local worker is unavailable.
                logger.warning(
                    "channel.ingress.worker_schedule_failed",
                    extra={"tenant_id": admission.tenant_id,
                           "inbox_id": admission.inbox_id,
                           "error_type": type(exc).__name__},
                )
        logger.info(
            "channel.ingress.admitted",
            extra={
                "tenant_id": admission.tenant_id,
                "user_id": admission.user_id,
                "connection_id": connection.connection_id,
                "correlation_id": admission.correlation_id,
                "inbox_id": admission.inbox_id,
                "new_event": admission.inserted,
            },
        )
        return admission

    async def _link_event(
        self, *, connection: ChannelConnection, event: InboundChannelEvent,
    ) -> VerifiedIdentityBinding:
        if (
            not self._is_link_command(event)
            or re.fullmatch(r"/link [A-Za-z0-9_-]{43}", event.text or "") is None
        ):
            raise ChannelAdmissionDenied("Not an authorized channel link proof")
        proof_digest = hashlib.sha256(
            event.text[len("/link "):].encode("ascii")
        ).hexdigest()
        binding = await self._repository.consume_verified_link(
            connection=connection,
            external_sender_id=event.external_sender_id,
            proof_digest=proof_digest,
        )
        if binding is None:
            raise ChannelAdmissionDenied("Channel link proof expired, used or rejected")
        logger.info(
            "channel.identity.linked",
            extra={
                "tenant_id": binding.tenant_id,
                "connection_id": binding.connection_id,
                "user_id": binding.user_id,
                "binding_id": binding.binding_id,
            },
        )
        return binding

    async def verify_and_admit(
        self, *,
        tenant_id: str, connection_id: str, adapter: ChannelAdapter,
        headers: Mapping[str, str], body: bytes,
    ) -> InboundAdmission:
        connection, event = await self._verify_native_event(
            tenant_id=tenant_id, connection_id=connection_id,
            adapter=adapter, headers=headers, body=body,
        )
        if not isinstance(event, InboundChannelEvent):
            raise ChannelAdmissionDenied("Single-message admission does not allow batches")
        return await self._admit_event(connection=connection, event=event)

    async def verify_and_link(
        self, *,
        tenant_id: str, connection_id: str, adapter: ChannelAdapter,
        headers: Mapping[str, str], body: bytes,
    ) -> VerifiedIdentityBinding:
        connection, event = await self._verify_native_event(
            tenant_id=tenant_id, connection_id=connection_id,
            adapter=adapter, headers=headers, body=body,
        )
        if not isinstance(event, InboundChannelEvent):
            raise ChannelAdmissionDenied("Single-link admission does not allow batches")
        return await self._link_event(connection=connection, event=event)

    async def verify_and_route_installed(
        self, *,
        tenant_id: str, connection_id: str,
        headers: Mapping[str, str], body: bytes,
    ) -> str:
        """One provider verification, then exactly one authorized persistence path.

        The installed adapter is selected by the tenant-scoped connection.
        Native headers/body cannot select executable code, AI provider, Karen
        principal or destination. A durable inbox receipt is not an AI answer.
        """
        initial = await self._repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if initial is None:
            # Disabled WhatsApp connections may receive delayed *status-only*
            # webhooks for already-finalized sends. Never reopen inbound chat,
            # sender linking, plugin execution, worker scheduling, or dispatch.
            disabled = await self._repository.get_connection(
                tenant_id=tenant_id, connection_id=connection_id,
            )
            if (
                disabled is None or disabled.enabled
                or disabled.tenant_id != tenant_id
                or disabled.connection_id != connection_id
                or disabled.installation_id != "whatsapp-cloud"
                or not isinstance(body, bytes)
                or not body
                or self._kernel.get_channel_activation_manifest(
                    disabled.installation_id
                ) is None
            ):
                raise ChannelAdmissionDenied("Channel connection is unavailable")
            historical_catalog = self._kernel.get_channel_activation_manifest(
                disabled.installation_id
            )
            declared_budget = getattr(
                historical_catalog.capabilities.communication_channel,
                "max_native_body_bytes", self._max_native_body_bytes,
            )
            if type(declared_budget) is not int or not 1 <= declared_budget <= 10_485_760:
                raise ChannelAdmissionDenied("Invalid historical channel body budget")
            if len(body) > min(self._max_native_body_bytes, declared_budget):
                raise ChannelNativeBodyTooLarge("Historical channel body exceeds transport budget")
            try:
                adapter = self._kernel.loader.load_extension(disabled.installation_id)
            except Exception:
                raise ChannelAdmissionDenied("Historical channel adapter unavailable") from None
            if not self._kernel.is_canonical_channel_adapter(
                disabled.installation_id, adapter,
            ):
                raise ChannelAdmissionDenied("Historical channel adapter not canonical")
            verifier = getattr(adapter, "normalize_deactivated_statuses", None)
            if not callable(verifier):
                raise ChannelAdmissionDenied("Historical channel status capability unavailable")
            try:
                statuses = await verifier(
                    connection=disabled, headers=headers, body=body,
                )
            except Exception as exc:
                logger.warning(
                    "channel.ingress.historical_status_verification_denied",
                    extra={
                        "tenant_id": tenant_id, "connection_id": connection_id,
                        "error_type": type(exc).__name__,
                    },
                )
                raise ChannelAdmissionDenied("Historical native status rejected") from None
            if (
                not isinstance(statuses, tuple)
                or not 1 <= len(statuses) <= 100
                or any(
                    not isinstance(status, ChannelProviderStatusEvent)
                    or status.connection_id != disabled.connection_id
                    for status in statuses
                )
            ):
                raise ChannelAdmissionDenied("Invalid historical native status batch")
            matched = 0
            for status in statuses:
                if await self._repository.record_deactivated_provider_status(
                    connection=disabled, status=status,
                ):
                    matched += 1
            logger.info(
                "channel.ingress.historical_status_committed",
                extra={
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "historical_status_count": len(statuses),
                    "matched_status_count": matched,
                    "inbound_count": 0,
                },
            )
            return "status_recorded" if matched else "ignored"
        if initial.tenant_id != tenant_id:
            raise ChannelAdmissionDenied("Channel connection is unavailable")
        if self._kernel.get_channel_activation_manifest(initial.installation_id) is None:
            raise ChannelAdmissionDenied("Installed channel is not available")
        try:
            adapter = self._kernel.loader.load_extension(initial.installation_id)
        except Exception:
            raise ChannelAdmissionDenied("Installed channel is unavailable") from None
        if not self._kernel.is_canonical_channel_adapter(
            initial.installation_id, adapter,
        ):
            raise ChannelAdmissionDenied("Noncanonical channel adapter")
        connection, event = await self._verify_native_event(
            tenant_id=tenant_id, connection_id=connection_id,
            adapter=adapter, headers=headers, body=body, allow_batch=True,
        )
        # Rotation between adapter resolution and signature verification must
        # not authorize a different installation.
        if (
            connection.installation_id != initial.installation_id
            or connection.revision != initial.revision
        ):
            raise ChannelAdmissionDenied("Channel connection changed during ingress")
        if isinstance(event, ChannelWebhookBatch):
            # A link token must never be combined with unrelated provider
            # messages or status receipts. Fail before mutating the ledger.
            link_events = [message for message in event.messages if self._is_link_command(message)]
            if link_events and (
                len(event.messages) != 1 or event.statuses or event.ignored_count
            ):
                raise ChannelAdmissionDenied("Link proof cannot share a native batch")
            if link_events:
                await self._link_event(connection=connection, event=link_events[0])
                return "linked"
            # Each inbox insert is idempotent; a partial provider retry will
            # never run the same user turn twice. Status rows have a separate
            # durable receipt path, never ChatRuntime, memory, or tool routing.
            for message in event.messages:
                await self._admit_event(connection=connection, event=message)
            for status in event.statuses:
                await self._repository.record_provider_status(
                    connection=connection, status=status,
                )
            logger.info(
                "channel.ingress.batch_processed",
                extra={
                    "tenant_id": connection.tenant_id,
                    "connection_id": connection.connection_id,
                    "inbound_count": len(event.messages),
                    "status_count": len(event.statuses),
                    "ignored_count": event.ignored_count,
                },
            )
            return "admitted" if event.messages else "status_recorded" if event.statuses else "ignored"
        if self._is_link_command(event):
            await self._link_event(connection=connection, event=event)
            return "linked"
        await self._admit_event(connection=connection, event=event)
        return "admitted"


__all__ = ["ChannelIngressService", "ChannelNativeBodyTooLarge"]
