"""Governed communication-channel host ingress and admission.

The transport plugin does not own memory, model routing, or ChatRuntime.
"""

from .ingress import ChannelIngressService

__all__ = ["ChannelIngressService"]
