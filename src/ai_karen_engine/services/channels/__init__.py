"""Governed communication-channel host ingress and admission.

The transport plugin does not own memory, model routing, or ChatRuntime.
"""

from .activation import ChannelActivationService
from .linking import ChannelLinkService
from .ingress import ChannelIngressService
from .execution import ChannelExecutionService
from .delivery import ChannelDeliveryService

__all__ = [
    "ChannelActivationService",
    "ChannelLinkService",
    "ChannelIngressService",
    "ChannelExecutionService",
    "ChannelDeliveryService",
]
