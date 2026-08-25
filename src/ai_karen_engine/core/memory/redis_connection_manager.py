"""
DEPRECATED: redis_connection_manager.py has moved to platform/memory/redis/

This module is a compatibility shim. Update imports to:
    from ai_karen_engine.platform.memory.redis.redis_connection_manager import ...

This shim will be removed in CORE-SPLIT-2 expiry (2026-09-30).
"""

from __future__ import annotations

import warnings

warnings.warn(
    "core.memory.redis_connection_manager is deprecated. "
    "Import from ai_karen_engine.platform.memory.redis.redis_connection_manager instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.platform.memory.redis.redis_connection_manager import *
