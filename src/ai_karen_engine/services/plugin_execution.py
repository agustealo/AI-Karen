"""Deprecated application compatibility exports for plugin execution results.

Execution authority lives in ``ai_karen_engine.extensions.executor`` and is
reached through ``PluginKernel``.  This module intentionally contains no
execution, sandbox, routing, policy, or registry logic.

Remove this shim after the HTTP plugin route imports these symbols directly
from ``services.plugin_service``.
"""

from ai_karen_engine.services.plugin_service import (
    ExecutionMode,
    ExecutionStatus,
    PluginExecutionResult,
)

ExecutionResult = PluginExecutionResult

__all__ = [
    "ExecutionMode",
    "ExecutionStatus",
    "ExecutionResult",
    "PluginExecutionResult",
]
