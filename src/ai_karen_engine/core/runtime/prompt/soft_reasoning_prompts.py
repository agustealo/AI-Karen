"""Versioned PromptRuntime definitions for Soft Reasoning.

Prompts live under Runtime because prompt assembly is a Runtime authority. Core
reasoning receives only prepared strings/contracts and never owns prompt text.

The templates are KAREN-authored operational equivalents of the verifier roles
described by Zhu et al. (ICML 2025); they do not copy the paper appendix text.
"""

from __future__ import annotations

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptDefinition,
    PromptLifecycleStatus,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import (
    PromptNotFoundError,
    PromptRegistry,
    VersionConflictError,
)

SOFT_REASONING_GENERATION_PROMPT_ID = "soft_reasoning.generation"
SOFT_REASONING_GENERATION_PROMPT_VERSION = "v1.0.0"
SOFT_REASONING_MULTI_GENERATE_PROMPT_ID = "soft_reasoning.multi_generate_verifier"
SOFT_REASONING_MULTI_GENERATE_PROMPT_VERSION = "v1.0.0"


SOFT_REASONING_GENERATION_PROMPT = PromptDefinition(
    prompt_id=SOFT_REASONING_GENERATION_PROMPT_ID,
    version=SOFT_REASONING_GENERATION_PROMPT_VERSION,
    name="Soft Reasoning Generation",
    description=(
        "Prepared generation contract for first-token embedding exploration. "
        "Runtime appends the model-specific insertion token as the final prompt token."
    ),
    system_instructions=(
        "Solve the user's task accurately. Reason using the supplied evidence and "
        "constraints. Return the answer in the response format requested by the user. "
        "Do not mention the embedding-search mechanism or the insertion token."
    ),
    token_budget=8192,
    allowed_overrides=["token_budget"],
    metadata={
        "capability": "soft_exploration",
        "research_family": "zhu_soft_reasoning_2025",
        "marker_placement": "last",
        "owner": "core.runtime.prompt",
    },
    status=PromptLifecycleStatus.ACTIVE,
    is_default=True,
)


SOFT_REASONING_MULTI_GENERATE_PROMPT = PromptDefinition(
    prompt_id=SOFT_REASONING_MULTI_GENERATE_PROMPT_ID,
    version=SOFT_REASONING_MULTI_GENERATE_PROMPT_VERSION,
    name="Soft Reasoning Multi-Generate Verifier",
    description=(
        "Batch verifier contract: inspect all candidate solutions together, solve the "
        "task independently using their useful reasoning, and emit one refined answer."
    ),
    system_instructions=(
        "You are the batch verification stage for Soft Reasoning. Inspect every "
        "candidate solution together with the original task and authorized evidence. "
        "Independently determine the best supported solution; candidates may all be "
        "wrong. Produce exactly one refined final answer. Do not vote by majority and "
        "do not reward stylistic similarity. Follow the requested answer format."
    ),
    token_budget=8192,
    allowed_overrides=["token_budget"],
    metadata={
        "capability": "soft_exploration",
        "verifier_strategy": "multi_generate",
        "research_family": "zhu_soft_reasoning_2025",
        "owner": "core.runtime.prompt",
    },
    status=PromptLifecycleStatus.ACTIVE,
    is_default=True,
)


SOFT_REASONING_PROMPTS = (
    SOFT_REASONING_GENERATION_PROMPT,
    SOFT_REASONING_MULTI_GENERATE_PROMPT,
)


def ensure_soft_reasoning_prompts(registry: PromptRegistry) -> None:
    """Idempotently seed canonical Soft Reasoning prompt definitions.

    Composition code must pass the canonical PromptRegistry. This function does
    not construct a registry and therefore cannot create a shadow prompt source.
    """

    for definition in SOFT_REASONING_PROMPTS:
        try:
            existing = registry.get_prompt(definition.prompt_id, definition.version)
        except PromptNotFoundError:
            try:
                registry.register_prompt(definition)
            except VersionConflictError:
                # Another concurrent composer may have registered the same version.
                registry.get_prompt(definition.prompt_id, definition.version)
            continue

        if existing.version != definition.version:
            raise RuntimeError(
                f"Soft Reasoning prompt registry mismatch for {definition.prompt_id}: "
                f"expected {definition.version}, got {existing.version}"
            )


__all__ = [
    "SOFT_REASONING_GENERATION_PROMPT",
    "SOFT_REASONING_GENERATION_PROMPT_ID",
    "SOFT_REASONING_GENERATION_PROMPT_VERSION",
    "SOFT_REASONING_MULTI_GENERATE_PROMPT",
    "SOFT_REASONING_MULTI_GENERATE_PROMPT_ID",
    "SOFT_REASONING_MULTI_GENERATE_PROMPT_VERSION",
    "SOFT_REASONING_PROMPTS",
    "ensure_soft_reasoning_prompts",
]
