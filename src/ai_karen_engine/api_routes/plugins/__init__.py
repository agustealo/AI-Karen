"""
Plugin API routes.

Exports routers for:
- General plugin management (list, execute, enable, disable)
- Intelligent Search plugin (run, status, capabilities)
"""

from .plugins import router as plugins_router, public_router as plugins_public_router
from .intelligent_search import router as intelligent_search_router

__all__ = [
    "plugins_router",
    "plugins_public_router",
    "intelligent_search_router",
]
