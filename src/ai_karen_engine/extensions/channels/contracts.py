"""Transport-only contracts for versioned communication-channel extensions.

Adapters authenticate their native protocol and normalize external identities.
Only the future host-owned Channel Gateway may bind a Karen principal, admit
a turn to ChatRuntime or persist delivery receipts. These declarations do not
grant runtime activation or authorize plugin execution.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


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



class PersonalSessionHealthState(str, Enum):
    """Health result is a vetted adapter observation, never an inferred DB state."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class PersonalPairingQR(_ChannelRecord):
    """Ephemeral sensitive QR; never persist/log this object.

    Only a vetted provider transport can supply a real QR. The host must
    enforce ownership, current consent, policy, session revision, single-use
    delivery, HTTPS and Cache-Control: no-store independently.
    """

    provider_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(min_length=1)
    connection_revision: int = Field(ge=1)
    session_reference: str = Field(min_length=1, max_length=256)
    qr_payload: SecretStr
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "PersonalPairingQR":
        if (
            self.issued_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or not self.qr_payload.get_secret_value()
            or self.expires_at <= self.issued_at
            or (self.expires_at - self.issued_at).total_seconds() > 300
        ):
            raise ValueError("QR must have a nonempty payload and bounded aware lifetime")
        return self


class PersonalSessionHealth(_ChannelRecord):
    """Vetted provider session probe; does not itself authenticate its source."""

    provider_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(min_length=1)
    connection_revision: int = Field(ge=1)
    session_reference: str = Field(min_length=1, max_length=256)
    state: PersonalSessionHealthState
    observed_at: datetime
    receipt_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def require_evidenced_state(self) -> "PersonalSessionHealth":
        if self.observed_at.tzinfo is None:
            raise ValueError("Provider health requires timezone-aware evidence")
        if self.state is PersonalSessionHealthState.CONNECTED and not self.receipt_id:
            raise ValueError("Connected requires an explicit provider receipt")
        return self


class PersonalSessionUnlinkReceipt(_ChannelRecord):
    """Provider's remote unlink acknowledgement, not credential-deletion proof."""

    provider_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(min_length=1)
    connection_revision: int = Field(ge=1)
    session_reference: str = Field(min_length=1, max_length=256)
    provider_receipt_id: str = Field(min_length=1, max_length=256)
    unlinked_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> "PersonalSessionUnlinkReceipt":
        if self.unlinked_at.tzinfo is None:
            raise ValueError("Provider unlink evidence must be timezone-aware")
        return self


class PersonalPairingTransport(Protocol):
    """Optional managed-provider capability, separate from normal channel send.

    The adapter translates verified native vendor responses into these models.
    None of these methods bypasses runtime plan/consent/RBAC/vault authority.
    Capability is not enabled by merely implementing this protocol.
    """

    async def issue_qr(self, *, connection: ChannelConnection) -> PersonalPairingQR: ...

    async def live_session_health(
        self, *, connection: ChannelConnection, session_reference: str,
    ) -> PersonalSessionHealth: ...

    async def unlink_session(
        self, *, connection: ChannelConnection, session_reference: str,
    ) -> PersonalSessionUnlinkReceipt: ...



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
    "PersonalPairingQR",
    "PersonalPairingTransport",
    "PersonalSessionHealth",
    "PersonalSessionHealthState",
    "PersonalSessionUnlinkReceipt",
    "InboundChannelEvent",
    "VerifiedIdentityBinding",
]
