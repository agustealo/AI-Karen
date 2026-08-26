"""
PromptRuntime service.

Coordinates prompt assembly, versioning, token budgeting, and validation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptDefinition,
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptVersion,
    PromptLifecycleStatus,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import (
    PromptRegistry,
    TokenEstimate,
    get_prompt_registry,
    register_prompt,
    get_prompt,
    PromptNotFoundError,
    TokenEstimateError,
)
from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler

logger = logging.getLogger("kari.runtime.prompt.service")


class PromptRuntimeService:
    """Service for prompt runtime operations."""
    
    def __init__(self, registry: Optional[PromptRegistry] = None):
        self.registry = registry or get_prompt_registry()
        self.assembler = PromptAssembler(self.registry)
    
    async def assemble_prompt(
        self,
        request: PromptAssemblyRequest,
        enforce_budget: bool = True,
        validate_schema: bool = True
    ) -> PromptAssemblyResult:
        """Assemble a prompt from request components."""
        
        # Get prompt definition if specified
        prompt_definition = None
        if request.prompt_id:
            try:
                prompt_definition = self.registry.get_prompt(
                    request.prompt_id,
                    request.prompt_version
                )
            except PromptNotFoundError:
                logger.warning(f"Prompt {request.prompt_id} not found, using assembly request")
        
        # Estimate tokens
        try:
            token_estimate = self.registry.estimate_tokens(request)
        except TokenEstimateError as e:
            logger.error(f"Token estimation failed: {e}")
            raise
        
        # Enforce token budget if requested
        if enforce_budget:
            budget_result = self.registry.enforce_token_budget(request, token_estimate)
            if not budget_result["budget_ok"]:
                logger.warning(f"Token budget exceeded: {budget_result['tokens_used']} > {request.token_budget}")
        
        # Assemble prompt
        assembly_result = await self.assembler.assemble_prompt(
            request,
            prompt_definition
        )
        
        # Validate output schema if requested
        if validate_schema and prompt_definition and prompt_definition.output_schema:
            validation_result = self.registry.validate_output_schema(
                prompt_definition.prompt_id,
                assembly_result.messages,
                prompt_definition.version
            )
            
            if not validation_result["valid"]:
                logger.warning(f"Output schema validation failed: {validation_result['errors']}")
        
        return assembly_result
    
    def get_prompt_definition(self, prompt_id: str, version: Optional[str] = None) -> PromptDefinition:
        """Get a prompt definition."""
        return self.registry.get_prompt(prompt_id, version)
    
    def register_prompt_definition(self, prompt: PromptDefinition) -> PromptDefinition:
        """Register a new prompt definition."""
        return self.registry.register_prompt(prompt)
    
    def list_prompt_definitions(self) -> List[PromptDefinition]:
        """List all prompt definitions."""
        return self.registry.list_prompts()
    
    def get_prompt_provenance(self, prompt_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Get provenance information for a prompt."""
        return self.registry.get_prompt_provenance(prompt_id, version)
    
    def validate_output(self, prompt_id: str, output: Any, version: Optional[str] = None) -> Dict[str, Any]:
        """Validate output against prompt schema."""
        return self.registry.validate_output_schema(prompt_id, output, version)
    
    def estimate_tokens(self, request: PromptAssemblyRequest) -> TokenEstimate:
        """Estimate token count for a prompt assembly request."""
        return self.registry.estimate_tokens(request)