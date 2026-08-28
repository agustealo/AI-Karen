"""PromptRuntime, canonical final prompt assembly authority.

PromptRuntime consumes trusted, already-authorized inputs from Runtime and owns
cross-section token pressure, persona presentation boundaries, omission
provenance, and final message assembly. It does not select providers, execute
tools, perform inference, or persist memory.
"""

from __future__ import annotations

from ai_karen_engine.core.runtime.prompt.persona_contract import (
    PERSONA_AUTHORITY_FIELDS,
    PERSONA_PRESENTATION_FIELDS,
    PersonaAssemblyPolicy,
    PersonaPromptContext,
    PersonaSanitizationResult,
    ProfileAssemblyPolicy,
    ProfilePromptContext,
)
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
    PromptNotFoundError,
    PromptRegistry,
    TokenEstimate,
    TokenEstimateError,
    VersionConflictError,
    get_prompt,
    get_prompt_registry,
    register_prompt,
)
from ai_karen_engine.core.runtime.prompt.prompt_service import (
    PromptRuntimeService,
    get_prompt_runtime_service,
)
from ai_karen_engine.core.runtime.prompt.truncation_policy import (
    HierarchicalTruncationPolicy,
    SectionPriority,
    SectionProtection,
    TruncationRule,
    TruncationStrategy,
)

__all__ = [
    "PERSONA_AUTHORITY_FIELDS",
    "PERSONA_PRESENTATION_FIELDS",
    "PersonaAssemblyPolicy",
    "PersonaPromptContext",
    "PersonaSanitizationResult",
    "ProfileAssemblyPolicy",
    "ProfilePromptContext",
    "PromptAssemblyRequest",
    "PromptAssemblyResult",
    "PromptDefinition",
    "PromptLifecycleStatus",
    "PromptTruncationEvent",
    "PromptVersion",
    "PromptAssembler",
    "PromptRegistry",
    "TokenEstimate",
    "PromptNotFoundError",
    "VersionConflictError",
    "TokenEstimateError",
    "get_prompt_registry",
    "register_prompt",
    "get_prompt",
    "PromptRuntimeService",
    "get_prompt_runtime_service",
    "HierarchicalTruncationPolicy",
    "SectionPriority",
    "SectionProtection",
    "TruncationRule",
    "TruncationStrategy",
]
