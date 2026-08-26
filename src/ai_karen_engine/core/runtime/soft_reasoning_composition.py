"""Runtime composition root for the strict Soft Reasoning research profile.

This module is the only place that joins provider/model authority, prompt
runtime, special-token lifecycle, the generation hook, the Multi-Generate
verifier, and Core's SoftReasoner. No component below this layer discovers a
provider or builds a shadow prompt registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ai_karen_engine.core.model_runtime.model_manager import (
    ModelManager,
    RuntimeSelection,
    get_model_manager,
)
from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpointType
from ai_karen_engine.core.model_runtime.provider_contracts import ProviderNotAvailable
from ai_karen_engine.core.reasoning.soft_reasoning.contracts import SoftVerificationScore
from ai_karen_engine.core.reasoning.soft_reasoning.exploration import (
    SoftExplorationConfig,
    SoftExplorationEngine,
)
from ai_karen_engine.core.reasoning.strategies.soft_strategy import SoftReasoner
from ai_karen_engine.core.runtime.prompt import (
    PromptRegistry,
    PromptRuntimeService,
    get_prompt_registry,
    get_prompt_runtime_service,
)
from ai_karen_engine.core.runtime.prompt.soft_reasoning_prompts import (
    SOFT_REASONING_GENERATION_PROMPT_ID,
    SOFT_REASONING_GENERATION_PROMPT_VERSION,
    ensure_soft_reasoning_prompts,
)
from ai_karen_engine.core.runtime.soft_reasoning_runtime import (
    TransformersGenerationSession,
    TransformersSoftGenerationAdapter,
    TransformersSoftReasoningConfig,
)
from ai_karen_engine.core.runtime.soft_reasoning_token import SoftReasoningTokenManager
from ai_karen_engine.core.runtime.soft_reasoning_verifier import RuntimeMultiGenerateVerifier


class SoftReasoningCompositionUnavailable(RuntimeError):
    pass


class _BatchVerifierSingleAdapter:
    """Protocol bridge; strict paper execution never calls this single path."""

    def __init__(self, batch: RuntimeMultiGenerateVerifier) -> None:
        self._batch = batch

    def score(
        self,
        objective: str,
        response: str,
        *,
        evidence: Sequence[str],
    ) -> SoftVerificationScore:
        result = self._batch.verify_batch(objective, [response], evidence=evidence)
        if len(result.candidate_scores) != 1:
            raise SoftReasoningCompositionUnavailable(
                "single-candidate verifier bridge received an invalid batch result"
            )
        return result.candidate_scores[0]


@dataclass(frozen=True, slots=True)
class ComposedSoftReasoning:
    strategy: SoftReasoner
    prepared_prompt: str
    prompt_version: str
    provider_id: str
    model_id: str
    runtime_engine: str
    marker_token: str
    marker_token_id: int
    profile: str
    maximum_total_model_calls: int


class RuntimeSoftReasoningComposer:
    """Compose SoftReasoner only from canonical Runtime-owned dependencies."""

    def __init__(
        self,
        *,
        model_manager: ModelManager,
        prompt_registry: PromptRegistry,
        prompt_service: PromptRuntimeService,
        token_manager: SoftReasoningTokenManager | None = None,
    ) -> None:
        self._models = model_manager
        self._registry = prompt_registry
        self._prompts = prompt_service
        self._tokens = token_manager or SoftReasoningTokenManager()
        ensure_soft_reasoning_prompts(self._registry)

    def compose_paper_2025(
        self,
        *,
        objective: str,
        evidence: Sequence[str] = (),
        preferred_provider: str | None = None,
        preferred_model: str | None = None,
    ) -> ComposedSoftReasoning:
        selection = self._select_transformers(preferred_provider)
        runtime = self._models.resolve_runtime(selection)
        if not isinstance(runtime, TransformersGenerationSession):
            raise SoftReasoningCompositionUnavailable(
                "selected runtime does not expose Transformers generation internals"
            )

        marker = self._tokens.ensure(runtime)
        generation = TransformersSoftGenerationAdapter(
            runtime,
            TransformersSoftReasoningConfig.paper_2025(marker.token_id),
        )
        capabilities = generation.capabilities()
        if preferred_model and preferred_model not in {"auto", capabilities.model_id}:
            raise SoftReasoningCompositionUnavailable(
                "the selected canonical local model does not match preferred_model"
            )
        if not capabilities.supports_logprobs:
            raise SoftReasoningCompositionUnavailable(
                "paper_2025 requires selected-token log probabilities"
            )

        batch_verifier = RuntimeMultiGenerateVerifier(
            runtime=runtime,
            prompt_registry=self._registry,
            prompt_service=self._prompts,
        )
        config = SoftExplorationConfig.paper_2025()
        engine = SoftExplorationEngine(
            generation=generation,
            verifier=_BatchVerifierSingleAdapter(batch_verifier),
            batch_verifier=batch_verifier,
            config=config,
        )
        prepared_prompt = self._prepare_generation_prompt(
            objective=objective,
            evidence=evidence,
            marker_token=marker.token,
        )
        generation.validate_prompt_contract(prepared_prompt)

        # initial k + four refinement batches, each followed by one verifier call
        batches = 1 + config.max_iterations
        maximum_total_model_calls = (
            config.initial_samples
            + config.max_iterations * config.batch_size
            + batches
        )
        return ComposedSoftReasoning(
            strategy=SoftReasoner(engine),
            prepared_prompt=prepared_prompt,
            prompt_version=SOFT_REASONING_GENERATION_PROMPT_VERSION,
            provider_id=selection.provider_id,
            model_id=capabilities.model_id,
            runtime_engine=capabilities.runtime_engine,
            marker_token=marker.token,
            marker_token_id=marker.token_id,
            profile=config.research_profile,
            maximum_total_model_calls=maximum_total_model_calls,
        )

    def _select_transformers(self, preferred_provider: str | None) -> RuntimeSelection:
        context = {
            "preferred_runtime_family": "transformers",
            "local_first": True,
        }
        if preferred_provider:
            context["preferred_provider"] = preferred_provider
        selection = self._models.select_provider(
            "text_generation",
            context=context,
            stream=False,
        )
        if selection is None:
            raise SoftReasoningCompositionUnavailable(
                "no text-generation runtime is available for Soft Reasoning"
            )
        if selection.endpoint_type != ProviderEndpointType.BUILTIN_TRANSFORMERS:
            raise SoftReasoningCompositionUnavailable(
                "paper_2025 requires a local Transformers runtime with model-internal access"
            )
        return selection

    def _prepare_generation_prompt(
        self,
        *,
        objective: str,
        evidence: Sequence[str],
        marker_token: str,
    ) -> str:
        definition = self._registry.get_prompt(
            SOFT_REASONING_GENERATION_PROMPT_ID,
            SOFT_REASONING_GENERATION_PROMPT_VERSION,
        )
        user_parts = ["TASK", objective.strip()]
        clean_evidence = [str(item).strip() for item in evidence if str(item).strip()]
        if clean_evidence:
            user_parts.extend(
                [
                    "AUTHORIZED EVIDENCE",
                    "\n".join(
                        f"[{index}] {item}"
                        for index, item in enumerate(clean_evidence, start=1)
                    ),
                ]
            )
        messages = [
            {"role": "system", "content": definition.system_instructions},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
        rendered = self._prompts.render_text_prompt(messages).rstrip()
        # Marker must be the final prompt token; the specialized runtime adapter
        # validates this after tokenizer-specific encoding.
        return f"{rendered}\n{marker_token}"


def get_runtime_soft_reasoning_composer() -> RuntimeSoftReasoningComposer:
    """Canonical application-level factory; no subsystem constructs its peers."""

    return RuntimeSoftReasoningComposer(
        model_manager=get_model_manager(),
        prompt_registry=get_prompt_registry(),
        prompt_service=get_prompt_runtime_service(),
    )


__all__ = [
    "ComposedSoftReasoning",
    "RuntimeSoftReasoningComposer",
    "SoftReasoningCompositionUnavailable",
    "get_runtime_soft_reasoning_composer",
]
