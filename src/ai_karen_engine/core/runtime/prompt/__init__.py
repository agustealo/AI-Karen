"""
PromptRuntime — canonical prompt assembly authority.

PromptRuntime is responsible for assembling the final prompt/messages
sent to ExpressionGateway. It consumes trusted inputs from:

- system/tenant policy
- persona/profile
- memory recall
- CORTEX analysis
- tool/plugin contracts
- workflow context
- provider capabilities
- token budget
- output schema

It does NOT:
- select providers
- execute tools
- perform inference
- persist memory
"""

from __future__ import annotations

from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler
from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptDefinition,
    PromptLifecycleStatus,
    PromptTruncationEvent,
    PromptVersion,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import (
    PromptRegistry,
    TokenEstimate,
    PromptNotFoundError,
    VersionConflictError,
    TokenEstimateError,
    get_prompt_registry,
    register_prompt,
    get_prompt,
)
from ai_karen_engine.core.runtime.prompt.prompt_service import PromptRuntimeService

__all__ = [
    # Core contracts
    "PromptAssemblyRequest",
    "PromptAssemblyResult",
    "PromptDefinition",
    "PromptLifecycleStatus",
    "PromptTruncationEvent",
    "PromptVersion",
    
    # Main assembler
    "PromptAssembler",
    
    # Registry
    "PromptRegistry",
    "TokenEstimate",
    "PromptNotFoundError",
    "VersionConflictError",
    "TokenEstimateError",
    "get_prompt_registry",
    "register_prompt",
    "get_prompt",
    
    # Service
    "PromptRuntimeService",
]
