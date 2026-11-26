"""Runtime composition root for the strict Soft Reasoning research profile.

This module is the only place that joins provider/model authority, prompt
runtime, special-token lifecycle, the generation hook, the Multi-Generate
verifier, and Core's SoftReasoner. No component below this layer discovers a
provider or builds a shadow prompt registry.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Sequence

from ai_karen_engine.core.model_runtime.governed_model_admission import GovernedToolModelAdmission
from ai_karen_engine.core.model_runtime.model_manager import (
    ModelManager,
    RuntimeSelection,
    get_model_manager,
)
from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpointType
from ai_karen_engine.core.model_runtime.provider_health_monitor import NativeExecutionSequence
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
    reserved_model_calls: Callable[[], int] | None = None


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
        execution_admission: GovernedToolModelAdmission | None = None,
        preparation_checkpoint: Callable[[], None] | None = None,
    ) -> ComposedSoftReasoning:
        if execution_admission is not None and preparation_checkpoint is None:
            raise SoftReasoningCompositionUnavailable("owned specialist preparation required")
        if preparation_checkpoint is not None:
            preparation_checkpoint()
        selection = self._select_transformers(preferred_provider)
        target = None
        endpoint = None
        if execution_admission is not None:
            # Live Runtime composition must validate the concrete native
            # target before even resolving the cached model object.
            endpoint = self._models._resolve_endpoint(selection.provider_id)
            if endpoint is None:
                raise SoftReasoningCompositionUnavailable("native endpoint unavailable")
            target = self._models.resolve_native_target(selection)
            execution_admission.require_native_generation(endpoint, model=target)
            if preferred_model and preferred_model != "auto" and (
                os.path.realpath(preferred_model) != os.path.realpath(target)
            ):
                raise SoftReasoningCompositionUnavailable(
                    "the selected canonical local model does not match preferred_model"
                )
        if preparation_checkpoint is not None:
            preparation_checkpoint()
        runtime = self._models.resolve_runtime(selection)
        if execution_admission is not None:
            from ai_karen_engine.core.model_runtime.providers.transformers_runtime import TransformersRuntime

            if not isinstance(runtime, TransformersRuntime) or target is None:
                raise SoftReasoningCompositionUnavailable("native runtime identity unavailable")
            # Never let generation_components silently load a fallback model.
            if not runtime.warm(target, exact_only=True, checkpoint=preparation_checkpoint):
                raise SoftReasoningCompositionUnavailable("authorized local model unavailable")
        if not callable(getattr(runtime, "generation_components", None)) or not callable(
            getattr(runtime, "runtime_capabilities", None)
        ):
            raise SoftReasoningCompositionUnavailable(
                "selected runtime does not expose Transformers generation internals"
            )

        pinned = None
        checkpoint: Callable[[], None] | None = preparation_checkpoint
        reserved = 0
        started = False
        pending_attempt = False
        observations = NativeExecutionSequence()
        if execution_admission is not None:
            if target is None or endpoint is None:
                raise SoftReasoningCompositionUnavailable("native target unavailable")
            with runtime.borrow_generation_components(target, checkpoint=preparation_checkpoint) as components:
                pinned = components
                marker = self._tokens.ensure(runtime)
                if preparation_checkpoint is not None:
                    preparation_checkpoint()
        else:
            marker = self._tokens.ensure(runtime)

        @contextmanager
        def model_scope():
            nonlocal pending_attempt
            if pinned is None:
                yield
                return
            # Only a successfully reserved exploration operation gets an
            # observation scope. Capability checks and preparation do not.
            if pending_attempt:
                pending_attempt = False
                with observations.attempt():
                    with runtime.borrow_generation_components(
                        target, expected=pinned, checkpoint=checkpoint,
                    ):
                        yield
            else:
                with runtime.borrow_generation_components(
                    target, expected=pinned, checkpoint=checkpoint,
                ):
                    yield
        def check_native() -> None:
            if checkpoint is None:
                raise SoftReasoningCompositionUnavailable("native worker scope unavailable")
            checkpoint()

        native_checkpoint = check_native if execution_admission is not None else None
        generation = TransformersSoftGenerationAdapter(
            runtime,
            TransformersSoftReasoningConfig.paper_2025(marker.token_id),
            checkpoint=native_checkpoint,
        )
        with model_scope():
            capabilities = generation.capabilities()
        if execution_admission is None and preferred_model and preferred_model not in {"auto", capabilities.model_id}:
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
            checkpoint=native_checkpoint,
        )
        config = SoftExplorationConfig.paper_2025()
        engine = SoftExplorationEngine(
            generation=generation,
            verifier=_BatchVerifierSingleAdapter(batch_verifier),
            batch_verifier=batch_verifier,
            config=config,
            model_scope=model_scope,
        )
        prepared_prompt = self._prepare_generation_prompt(
            objective=objective,
            evidence=evidence,
            marker_token=marker.token,
        )
        with model_scope():
            generation.validate_prompt_contract(prepared_prompt)

        def record_reservation() -> None:
            nonlocal reserved
            reserved += 1

        def reserved_model_calls() -> int:
            return reserved

        async def run_exploration(prompt, *, on_model_attempt, **kwargs):
            nonlocal started
            if started or execution_admission is None or endpoint is None or target is None:
                raise SoftReasoningCompositionUnavailable("specialist execution scope unavailable")
            started = True

            def execute(worker_checkpoint, reserve):
                nonlocal checkpoint, pending_attempt
                checkpoint = worker_checkpoint

                def attempt():
                    nonlocal pending_attempt
                    reserve()
                    on_model_attempt()
                    pending_attempt = True

                try:
                    worker_checkpoint()
                    trace = engine.explore(prompt, on_model_attempt=attempt, **kwargs)
                    worker_checkpoint()
                    return trace
                finally:
                    checkpoint = None
                    pending_attempt = False

            try:
                trace = await execution_admission.run_native_attempt_sequence(
                    endpoint, model=target, function=execute, on_reserved=record_reservation,
                )
            except (Exception, asyncio.CancelledError) as exc:
                observations.finish(exc)
                raise
            observations.finish()
            return trace

        if preparation_checkpoint is not None:
            preparation_checkpoint()
        checkpoint = None  # never reuse a retired preparation worker's checkpoint
        maximum_total_model_calls = config.maximum_total_model_calls
        return ComposedSoftReasoning(
            strategy=SoftReasoner(
                engine, run_exploration=run_exploration if execution_admission is not None else None,
            ),
            prepared_prompt=prepared_prompt,
            prompt_version=SOFT_REASONING_GENERATION_PROMPT_VERSION,
            provider_id=selection.provider_id,
            model_id=capabilities.model_id,
            runtime_engine=capabilities.runtime_engine,
            marker_token=marker.token,
            marker_token_id=marker.token_id,
            profile=config.research_profile,
            maximum_total_model_calls=maximum_total_model_calls,
            reserved_model_calls=reserved_model_calls if execution_admission is not None else None,
        )

    def _select_transformers(self, preferred_provider: str | None) -> RuntimeSelection:
        context: dict[str, object] = {
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
        return f"{rendered}\n{marker_token}"


def get_runtime_soft_reasoning_composer() -> RuntimeSoftReasoningComposer:
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
