"""
DEPRECATED: error_middleware has moved to platform/errors/middleware.py

This module is a compatibility shim. Update imports to:
    from ai_karen_engine.platform.errors.middleware import PlatformErrorMiddleware

This shim will be removed in CORE-SPLIT-2 expiry (2026-09-30).
"""

from __future__ import annotations

import warnings

warnings.warn(
    "core.errors.middleware is deprecated. "
    "Import from ai_karen_engine.platform.errors.middleware instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.platform.errors.middleware import PlatformErrorMiddleware  # noqa: F401
