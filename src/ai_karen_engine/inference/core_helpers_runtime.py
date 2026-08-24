"""
Deprecated shim: execution adapters moved to core/model_runtime/providers/.

Import from the canonical location instead:

    from ai_karen_engine.core.model_runtime.providers.core_helpers_runtime import (
        CoreHelpersRuntime,
    )
"""

import warnings

warnings.warn(
    "ai_karen_engine.inference.core_helpers_runtime is deprecated. "
    "Use ai_karen_engine.core.model_runtime.providers.core_helpers_runtime instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.model_runtime.providers.core_helpers_runtime import (
    CoreHelpersRuntime,
)

__all__ = ["CoreHelpersRuntime"]
