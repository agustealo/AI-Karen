from __future__ import annotations

"""Compatibility import for the canonical CORTEX executive.

The cognitive decision authority lives in ``ai_karen_engine.core.cortex.executive``.
This module remains only so existing runtime imports continue to work while call
sites converge. New code must import CORTEX from ``core.cortex`` or
``core.cortex.executive``.
"""

from ai_karen_engine.core.cortex.executive import (
    CortexExecutionDecider,
    get_cortex_execution_decider,
)

__all__ = ["CortexExecutionDecider", "get_cortex_execution_decider"]
