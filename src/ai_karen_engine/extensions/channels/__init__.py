"""Host-governed communication channel contracts.

No channel is active until the canonical Channel Gateway provides verified
identity binding, durable admission and authenticated delivery.
"""

from .contracts import (
    ChannelAdapter,
    ChannelCapabilitySet,
    ChannelConnection,
    ChannelDeliveryReceipt,
    ChannelDeliveryRequest,
    ChannelDeliveryState,
    InboundChannelEvent,
    VerifiedIdentityBinding,
)

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
