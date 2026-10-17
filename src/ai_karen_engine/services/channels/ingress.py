"""Host-owned authenticated transport ingress for communication extensions.

This stage performs verified protocol admission into a durable, tenant-RLS inbox.
It deliberately does NOT claim to process or deliver a chat turn. Subsequent
gateway stages own fresh principal validation, ChatRuntime execution and outbox.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Mapping

from ai_karen_engine.extensions.channels.contracts import (
    ChannelAdapter,
    ChannelConnection,
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


class ChannelIngressService:
    """Resolve installed transport authority, verify native data, admit once."""

    def __init__(
        self,
        *,
        kernel: PluginKernel,
        repository: SqlChannelRepository,
        max_native_body_bytes: int,
    ) -> None:
        if not 1 <= max_native_body_bytes <= 10_485_760:
            raise ValueError("Invalid channel request body budget")
        self._kernel = kernel
        self._repository = repository
        self._max_native_body_bytes = max_native_body_bytes

    async def _verify_native_event(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        adapter: ChannelAdapter,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[ChannelConnection, InboundChannelEvent]:
        """Authenticate a native event using one shared, host-governed path."""
        if not tenant_id or not connection_id:
            raise ChannelAdmissionDenied("Host tenant and connection are required")
        if not isinstance(body, bytes):
            raise ValueError("Native channel body must be bytes")
        if len(body) > self._max_native_body_bytes:
            raise ValueError("Native channel body exceeds configured budget")

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
        if not isinstance(event, InboundChannelEvent):
            raise ChannelAdmissionDenied("Adapter returned invalid event contract")
        if event.connection_id != connection.connection_id:
            raise ChannelAdmissionDenied("Adapter event connection mismatch")

        if event.message_kind not in channel_capability.inbound:
            raise ChannelAdmissionDenied("Unsupported inbound channel message kind")
        return connection, event

    async def verify_and_admit(
        self, *,
        tenant_id: str, connection_id: str, adapter: ChannelAdapter,
        headers: Mapping[str, str], body: bytes,
    ) -> InboundAdmission:
        """Never admit a link proof to ChatRuntime or its durable conversation."""
        connection, event = await self._verify_native_event(
            tenant_id=tenant_id, connection_id=connection_id,
            adapter=adapter, headers=headers, body=body,
        )
        if (
            event.message_kind == "text"
            and isinstance(event.text, str)
            and re.match(r"^/link(?:\\s|$)", event.text)
        ):
            raise ChannelAdmissionDenied("Link proofs use identity admission only")
        admission = await self._repository.admit_verified_inbound(
            connection=connection,
            event=event,
        )
        logger.info(
            "channel.ingress.admitted",
            extra={
                "tenant_id": admission.tenant_id,
                "user_id": admission.user_id,
                "connection_id": connection_id,
                "correlation_id": admission.correlation_id,
                "inbox_id": admission.inbox_id,
                "new_event": admission.inserted,
            },
        )
        return admission


    async def verify_and_link(
        self, *,
        tenant_id: str, connection_id: str, adapter: ChannelAdapter,
        headers: Mapping[str, str], body: bytes,
    ) -> VerifiedIdentityBinding:
        """Consume a host-issued proof ONLY after native webhook verification.

        Provider event user/tenant claims are never trusted. The DB challenge
        resolves Karen identity under RLS, and the proof text bypasses chat
        memory, logs, and the normal message inbox entirely.
        """
        connection, event = await self._verify_native_event(
            tenant_id=tenant_id, connection_id=connection_id,
            adapter=adapter, headers=headers, body=body,
        )
        if (
            event.message_kind != "text"
            or not isinstance(event.text, str)
            or re.fullmatch(r"/link [A-Za-z0-9_-]{43}", event.text) is None
        ):
            raise ChannelAdmissionDenied("Not an authorized channel link proof")
        token = event.text[len("/link "):]
        proof_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
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


__all__ = ["ChannelIngressService"]
