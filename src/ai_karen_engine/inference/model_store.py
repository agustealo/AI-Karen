"""
Deprecated shim: ModelStore moved to core/model_runtime/model_store.py.

Import from the canonical location instead:

    from ai_karen_engine.core.model_runtime.model_store import (
        ModelStore,
        ModelDescriptor,
        LocalModel,
    )
"""

import warnings

warnings.warn(
    "ai_karen_engine.inference.model_store is deprecated. "
    "Use ai_karen_engine.core.model_runtime.model_store instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.model_runtime.model_store import (
    LocalModel,
    ModelDescriptor,
    ModelStore,
    get_model_store,
    initialize_model_store,
    list_models,
    get_model,
    register_model,
    scan_local_models,
)

__all__ = [
    "ModelStore",
    "ModelDescriptor",
    "LocalModel",
    "get_model_store",
    "initialize_model_store",
    "list_models",
    "get_model",
    "register_model",
    "scan_local_models",
]
