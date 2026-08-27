"""Compatibility ASGI export for legacy ``server.app`` consumers.

Canonical application construction lives in ``ai_karen_engine.app``. This
module intentionally contains no FastAPI composition, lifecycle, router wiring,
or shutdown authority.
"""

from ai_karen_engine.app import create_app

app = create_app()

__all__ = ["app", "create_app"]
