"""Plugin API routes.

Exports the canonical plugin runtime and public read-only routers.
"""

from .plugins import router as plugins_router, public_router as plugins_public_router

__all__ = [
    "plugins_router",
    "plugins_public_router",
]
