"""Compatibility shim for the canonical AI KAREN router registry.

Application-level router and authentication authority lives in
``ai_karen_engine.server.routers``. Legacy imports from ``server.routers`` are
kept temporarily so external launchers can migrate without retaining a second
router implementation.
"""

from ai_karen_engine.server.routers import (
    CORE_ROUTERS,
    RouterSpec,
    configure_authentication_middleware,
    wire_routers,
)

__all__ = [
    "CORE_ROUTERS",
    "RouterSpec",
    "configure_authentication_middleware",
    "wire_routers",
]
