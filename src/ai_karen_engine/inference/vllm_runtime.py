"""
Deprecated shim: execution adapters moved to core/model_runtime/providers/.

Import from the canonical location instead:

    from ai_karen_engine.core.model_runtime.providers.vllm_runtime import VLLMRuntime
"""

import warnings

warnings.warn(
    "ai_karen_engine.inference.vllm_runtime is deprecated. "
    "Use ai_karen_engine.core.model_runtime.providers.vllm_runtime instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.model_runtime.providers.vllm_runtime import (
    VLLMRuntime,
)

__all__ = ["VLLMRuntime"]
