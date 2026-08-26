"""Core-facing service helpers.

Runtime owns live service resolution and lifecycle. This package retains only
base service primitives, the lightweight dependency-injection container, and
FastAPI dependency adapters. Do not add another service registry or lifecycle
manager here.
"""

from __future__ import annotations

from ai_karen_engine.core.services.base import BaseService, ServiceConfig, ServiceStatus
from ai_karen_engine.core.services.container import ServiceContainer, get_container, inject, service

__all__ = [
    "BaseService",
    "ServiceConfig",
    "ServiceStatus",
    "ServiceContainer",
    "get_container",
    "inject",
    "service",
]
