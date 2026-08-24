"""
Deprecated shim: execution adapters moved to core/model_runtime/providers/.

Import from the canonical location instead:

    from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
        TransformersRuntime,
    )
"""

import warnings

warnings.warn(
    "ai_karen_engine.inference.transformers_runtime is deprecated. "
    "Use ai_karen_engine.core.model_runtime.providers.transformers_runtime instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
    TransformersRuntime,
)

__all__ = ["TransformersRuntime"]
