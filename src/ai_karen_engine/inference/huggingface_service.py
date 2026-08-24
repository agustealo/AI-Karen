"""
Deprecated shim: HuggingFace service moved to core/model_runtime/huggingface_service.py.

Import from the canonical location instead:

    from ai_karen_engine.core.model_runtime.huggingface_service import (
        HuggingFaceService,
        EnhancedHuggingFaceService,
    )
"""

import warnings

warnings.warn(
    "ai_karen_engine.inference.huggingface_service is deprecated. "
    "Use ai_karen_engine.core.model_runtime.huggingface_service instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.model_runtime.huggingface_service import (
    EnhancedHuggingFaceService,
    HuggingFaceService,
    ModelFilters,
    TrainingFilters,
    TrainableModel,
)

__all__ = [
    "HuggingFaceService",
    "EnhancedHuggingFaceService",
    "ModelFilters",
    "TrainingFilters",
    "TrainableModel",
]
