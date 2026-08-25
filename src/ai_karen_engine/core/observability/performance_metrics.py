"""
DEPRECATED: performance_metrics has moved to platform/observability/metrics.py

This module is a compatibility shim. Update imports to:
    from ai_karen_engine.platform.observability.metrics import ...

This shim will be removed in CORE-SPLIT-2 expiry (2026-09-30).
"""

from __future__ import annotations

import warnings

warnings.warn(
    "core.observability.performance_metrics is deprecated. "
    "Import from ai_karen_engine.platform.observability.metrics instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.platform.observability.metrics import *  # noqa: F401,F403
