"""PromptRuntime service.

Coordinates prompt assembly, versioning, token budgeting, and validation.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler
from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptDefinition,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import (
    PromptNotFoundError,
    PromptRegistry,
    TokenEstimate,
    TokenEstimateError,
    get_prompt_registry,
)
from ai_karen_engine.core.runtime.prompt.truncation_policy import (
    HierarchicalTruncationPolicy,
)

logger = logging.getLogger("kari.runtime.prompt.service")


class PromptRuntimeService:
    """Canonical service for final prompt preparation.

    Domain owners supply already-authorized/ranked inputs. PromptRuntime owns
    cross-section token pressure, omission provenance, and final serialization.
    """

    def __init__(
        self,
        registry: Optional[PromptRegistry] = None,
        truncation_policy: Optional[HierarchicalTruncationPolicy] = None,
    ) -> None:
        self.registry = registry or get_prompt_registry()
        self.assembler = PromptAssembler(self.registry)
        self.truncation_policy = truncation_policy or HierarchicalTruncationPolicy()

    async def assemble_prompt(
        self,
        request: PromptAssemblyRequest,
        enforce_budget: bool = True,
        validate_schema: bool = True,
    ) -> PromptAssemblyResult:
        """Assemble a prompt from trusted runtime inputs."""

        working_request = copy.deepcopy(request)
        prompt_definition = None
        if working_request.prompt_id:
            try:
                prompt_definition = self.registry.get_prompt(
                    working_request.prompt_id,
                    working_request.prompt_version,
                )
            except PromptNotFoundError:
                logger.warning(
                    "Prompt %s not found; using explicit assembly request",
                    working_request.prompt_id,
                )

        try:
            initial_estimate = self.registry.estimate_tokens(working_request)
        except TokenEstimateError:
            logger.exception("Prompt token estimation failed")
            raise

        truncation_events = []
        if enforce_budget and initial_estimate.total_tokens > working_request.token_budget:
            truncation_events = self.truncation_policy.enforce(
                working_request,
                self.registry.estimate_tokens,
            )

        final_estimate = self.registry.estimate_tokens(working_request)
        if final_estimate.total_tokens > working_request.token_budget:
            logger.warning(
                "Prompt remains above budget after protected-section enforcement: %s > %s",
                final_estimate.total_tokens,
                working_request.token_budget,
            )

        assembly_result = await self.assembler.assemble_prompt(
            working_request,
            prompt_definition,
        )
        assembly_result.token_estimate = final_estimate.total_tokens
        assembly_result.truncation_events = truncation_events
        assembly_result.metadata.setdefault("context_policy", {})
        assembly_result.metadata["context_policy"].update(
            {
                "initial_tokens": initial_estimate.total_tokens,
                "final_tokens": final_estimate.total_tokens,
                "token_budget": working_request.token_budget,
                "truncation_count": len(truncation_events),
                "policy": "hierarchical_prompt_truncation",
            }
        )

        if validate_schema and prompt_definition and prompt_definition.output_schema:
            validation_result = self.registry.validate_output_schema(
                prompt_definition.prompt_id,
                assembly_result.messages,
                prompt_definition.version,
            )
            if not validation_result["valid"]:
                logger.warning(
                    "Output schema validation failed for %s: %s",
                    prompt_definition.prompt_id,
                    validation_result["errors"],
                )

        return assembly_result

    def get_prompt_definition(
        self,
        prompt_id: str,
        version: Optional[str] = None,
    ) -> PromptDefinition:
        return self.registry.get_prompt(prompt_id, version)

    def register_prompt_definition(self, prompt: PromptDefinition) -> PromptDefinition:
        return self.registry.register_prompt(prompt)

    def list_prompt_definitions(self) -> List[PromptDefinition]:
        return self.registry.list_prompts()

    def get_prompt_provenance(
        self,
        prompt_id: str,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.registry.get_prompt_provenance(prompt_id, version)

    def validate_output(
        self,
        prompt_id: str,
        output: Any,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.registry.validate_output_schema(prompt_id, output, version)

    def estimate_tokens(self, request: PromptAssemblyRequest) -> TokenEstimate:
        return self.registry.estimate_tokens(request)


_prompt_runtime_service: Optional[PromptRuntimeService] = None


def get_prompt_runtime_service() -> PromptRuntimeService:
    """Return the process-local PromptRuntime service facade.

    The service is stateless for request execution aside from the canonical
    prompt registry cache. Runtime remains the orchestration authority.
    """

    global _prompt_runtime_service
    if _prompt_runtime_service is None:
        _prompt_runtime_service = PromptRuntimeService()
    return _prompt_runtime_service
