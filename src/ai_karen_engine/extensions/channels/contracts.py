"""Transport-only contracts for versioned communication-channel extensions.

Adapters authenticate their native protocol and normalize external identities.
Only the future host-owned Channel Gateway may bind a Karen principal, admit
a turn to ChatRuntime or persist delivery receipts. These declarations do not
grant runtime activation or authorize plugin execution.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field


class _ChannelRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChannelConnection(_ChannelRecord):
    """Host-managed tenant-scoped connection to an installed adapter package."""

    connection_id: str = Field(min_length=1)
    installation_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    provider_account_id: str = Field(min_length=1)
    credential_handle: str = Field(min_length=1)
    revision: int = Field(ge=1)
    enabled: bool = False


class ChannelCapabilitySet(_ChannelRecord):
    """Negotiated message support, not a hardcoded provider list."""

    inbound: frozenset[str]
    outbound: frozenset[str]
    supports_edits: bool = False
    supports_streaming: bool = False
    supports_media: bool = False
    supports_delivery_receipts: bool = False


class InboundChannelEvent(_ChannelRecord):
    """Untrusted sender metadata: intentionally has no Karen principal fields."""

    connection_id: str = Field(min_length=1)
    external_event_id: str = Field(min_length=1)
    external_sender_id: str = Field(min_length=1)
    external_conversation_id: str = Field(min_length=1)
    message_kind: str = Field(min_length=1)
    text: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class VerifiedIdentityBinding(_ChannelRecord):
    """Host-attested identity after linking and tenant-policy verification."""

    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)
    external_sender_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class ChannelDeliveryRequest(_ChannelRecord):
    """Host-admitted outgoing message. Delivery does not imply model execution."""

    delivery_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    message_kind: str = Field(min_length=1)
    text: str | None = None


class ChannelDeliveryState(str, Enum):
    ACCEPTED = "accepted"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ChannelDeliveryReceipt(_ChannelRecord):
    """Provider-evidenced status; the host must reconcile unsupported states."""

    delivery_id: str = Field(min_length=1)
    state: ChannelDeliveryState
    provider_message_id: str | None = None
    provider_receipt_id: str | None = None
    error_code: str | None = None


class ChannelAdapter(Protocol):
    """Provider-facing transport interface; never receives ChatRuntime authority."""

    async def validate_config(self, settings: Mapping[str, Any]) -> None: ...

    async def verify_event(
        self,
        *,
        connection: ChannelConnection,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool: ...

    async def normalize_event(
        self,
        *,
        connection: ChannelConnection,
        headers: Mapping[str, str],
        body: bytes,
    ) -> InboundChannelEvent: ...

    async def send(
        self,
        *,
        connection: ChannelConnection,
        delivery: ChannelDeliveryRequest,
    ) -> ChannelDeliveryReceipt: ...

    async def health(self, *, connection: ChannelConnection) -> Mapping[str, Any]: ...

    async def start(self, *, connection: ChannelConnection) -> None: ...

    async def stop(self, *, connection: ChannelConnection) -> None: ...


__all__ = [
    "ChannelAdapter",
    "ChannelCapabilitySet",
    "ChannelConnection",
    "ChannelDeliveryReceipt",
    "ChannelDeliveryRequest",
    "ChannelDeliveryState",
    "InboundChannelEvent",
    "VerifiedIdentityBinding",
]
