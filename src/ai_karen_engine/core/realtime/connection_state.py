"""Realtime connection state enumeration.

Honest connectivity states for UI rendering.
"""

from __future__ import annotations

from enum import Enum


class ConnectionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
