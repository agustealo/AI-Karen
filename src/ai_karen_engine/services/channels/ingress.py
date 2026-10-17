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
            and re.match(r"^/link(?:\s|$)", event.text) is not None
        )

    async def _admit_event(
        self, *, connection: ChannelConnection, event: InboundChannelEvent,
    ) -> InboundAdmission:
        if self._is_link_command(event):
            raise ChannelAdmissionDenied("Link proofs use identity admission only")
        admission = await self._repository.admit_verified_inbound(
            connection=connection, event=event,
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
        if initial is None or initial.tenant_id != tenant_id:
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
            adapter=adapter, headers=headers, body=body,
        )
        # Rotation between adapter resolution and signature verification must
        # not authorize a different installation.
        if (
            connection.installation_id != initial.installation_id
            or connection.revision != initial.revision
        ):
            raise ChannelAdmissionDenied("Channel connection changed during ingress")
        if self._is_link_command(event):
            await self._link_event(connection=connection, event=event)
            return "linked"
        await self._admit_event(connection=connection, event=event)
        return "admitted"


__all__ = ["ChannelIngressService"]
