"""
DEPRECATED: security has moved to platform/security/encryption.py

This module is a compatibility shim. Update imports to:
    from ai_karen_engine.platform.security.encryption import ...

This shim will be removed in CORE-SPLIT-2 expiry (2026-09-30).
"""

from __future__ import annotations

import warnings

warnings.warn(
    "core.security.security is deprecated. "
    "Import from ai_karen_engine.platform.security.encryption instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.platform.security.encryption import *  # noqa: F401,F403
