from __future__ import annotations

"""Compatibility import for the canonical CORTEX executive.

The cognitive decision authority lives in ``ai_karen_engine.core.cortex.executive``.
Process-wide instance ownership lives in ``core.runtime.composition``. This module
remains only so existing runtime imports continue to work while call sites
converge. New code should receive CORTEX through explicit runtime composition.
"""

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.composition import get_cortex_execution_decider

__all__ = ["CortexExecutionDecider", "get_cortex_execution_decider"]
