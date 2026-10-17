"""Host-owned authenticated transport ingress for communication extensions.

This stage performs verified protocol admission into a durable, tenant-RLS inbox.
It deliberately does NOT claim to process or deliver a chat turn. Subsequent
gateway stages own fresh principal validation, ChatRuntime execution and outbox.
"""

from __future__ import annotations

import logging
from typing import Mapping

from ai_karen_engine.extensions.channels.contracts import (
    ChannelAdapter,
    InboundChannelEvent,
)
from ai_karen_engine.extensions.contracts import ExtensionLifecycleState
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

    async def verify_and_admit(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        adapter: ChannelAdapter,
        headers: Mapping[str, str],
        body: bytes,
    ) -> InboundAdmission:
        """No external principal or model answer is accepted from an adapter."""
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

        registration = self._kernel.runtime_registry.get(connection.installation_id)
        if registration is None or registration.state is not ExtensionLifecycleState.ENABLED:
            raise ChannelAdmissionDenied("Transport extension is not enabled")
        channel_capability = next(
            (c for c in registration.manifest.capabilities
             if c.id == "communication_channel"),
            None,
        )
        if channel_capability is None:
            raise ChannelAdmissionDenied("Installed extension is not a channel")

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

        declared = registration.manifest.metadata.get("communication_channel")
        if not isinstance(declared, dict):
            raise ChannelAdmissionDenied("Channel contract metadata is unavailable")
        if event.message_kind not in declared.get("inbound", []):
            raise ChannelAdmissionDenied("Unsupported inbound channel message kind")
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


__all__ = ["ChannelIngressService"]
