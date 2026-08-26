"""Deprecated Core security package boundary.

Security mechanics moved to :mod:`ai_karen_engine.platform.security` during
CORE-SPLIT-2. This package remains only as a narrow compatibility boundary for
callers that import the validator/encryption classes from ``core.security``.
It must not advertise symbols that the platform implementation no longer owns.
"""

from ai_karen_engine.platform.security.encryption import (
    PlatformContentEncryption,
    PlatformSecurityValidator,
)

# Compatibility aliases with an explicit sunset in the underlying Core shim.
SecurityValidator = PlatformSecurityValidator
ContentEncryption = PlatformContentEncryption

__all__ = [
    "ContentEncryption",
    "PlatformContentEncryption",
    "PlatformSecurityValidator",
    "SecurityValidator",
]
