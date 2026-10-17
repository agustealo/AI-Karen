"""Governed communication-channel host ingress and admission.

The transport plugin does not own memory, model routing, or ChatRuntime.
"""

from .ingress import ChannelIngressService
from .execution import ChannelExecutionService

__all__ = ["ChannelIngressService"]
