"""
DEPRECATED: ledger_models.py has moved to platform/memory/postgres/

This module is a compatibility shim. Update imports to:
    from ai_karen_engine.platform.memory.postgres.ledger_models import ...

This shim will be removed in CORE-SPLIT-2 expiry (2026-09-30).
"""

from __future__ import annotations

import warnings

warnings.warn(
    "core.memory.ledger_models is deprecated. "
    "Import from ai_karen_engine.platform.memory.postgres.ledger_models instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.platform.memory.postgres.ledger_models import *
