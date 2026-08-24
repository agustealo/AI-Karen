"""
Deprecated shim: inference namespace moved to core/model_runtime/.

Import from canonical locations instead:

    from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
        TransformersRuntime,
    )
    from ai_karen_engine.core.model_runtime.providers.vllm_runtime import VLLMRuntime
    from ai_karen_engine.core.model_runtime.providers.core_helpers_runtime import (
        CoreHelpersRuntime,
    )
    from ai_karen_engine.core.model_runtime.huggingface_service import (
        HuggingFaceService,
    )
    from ai_karen_engine.core.model_runtime.model_store import ModelStore
"""

import warnings

warnings.warn(
    "ai_karen_engine.inference is deprecated. "
    "Use ai_karen_engine.core.model_runtime.* instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
    TransformersRuntime,
)
from ai_karen_engine.core.model_runtime.providers.vllm_runtime import (
    VLLMRuntime,
)
from ai_karen_engine.core.model_runtime.providers.core_helpers_runtime import (
    CoreHelpersRuntime,
)
from ai_karen_engine.core.model_runtime.huggingface_service import (
    EnhancedHuggingFaceService,
    HuggingFaceService,
    ModelFilters,
    TrainingFilters,
    TrainableModel,
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
from ai_karen_engine.inference.factory import (
    InferenceServiceConfig,
    InferenceServiceFactory,
    get_inference_service_factory,
    get_local_gguf_runtime,
    get_transformers_runtime,
    get_model_store as _get_model_store_factory,
)

__all__ = [
    "TransformersRuntime",
    "VLLMRuntime",
    "CoreHelpersRuntime",
    "ModelStore",
    "ModelDescriptor",
    "LocalModel",
    "HuggingFaceService",
    "EnhancedHuggingFaceService",
    "ModelFilters",
    "TrainingFilters",
    "TrainableModel",
    "InferenceServiceConfig",
    "InferenceServiceFactory",
    "get_inference_service_factory",
    "get_local_gguf_runtime",
    "get_transformers_runtime",
    "get_model_store",
    "initialize_model_store",
    "list_models",
    "get_model",
    "register_model",
    "scan_local_models",
]
