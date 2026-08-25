"""
DEPRECATED: This module is deprecated and will be removed in version 0.4.0.

vLLM is no longer supported as a built-in provider. To use vLLM, configure it as a
custom OpenAI-compatible provider instead:

Example configuration:
```json
{
  "name": "custom-local-vllm",
  "display_name": "vLLM Local Server",
  "provider_type": "custom",
  "compatibility_profile": "openai_compatible",
  "base_url": "http://localhost:8000/v1",
  "requires_api_key": false
}
```

For Docker deployments, use: http://host.docker.internal:8000/v1
For Kubernetes deployments, use the appropriate service URL.

This module now redirects imports from the canonical location for backward compatibility only.
"""

import warnings

warnings.warn(
    "ai_karen_engine.inference.vllm_runtime is deprecated. "
    "Configure vLLM as a custom OpenAI-compatible provider instead. "
    "Use ai_karen_engine.core.model_runtime.providers.vllm_runtime only for migration purposes. "
    "This module will be removed in version 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

from ai_karen_engine.core.model_runtime.providers.vllm_runtime import (
    VLLMRuntime,
)

DEPRECATED = True
REPLACEMENT = "custom_openai_compatible provider"
SUNSET_VERSION = "0.4.0"

__all__ = ["VLLMRuntime"]
