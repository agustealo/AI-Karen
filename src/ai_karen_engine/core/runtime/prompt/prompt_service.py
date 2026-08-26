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

    def build_request_from_runtime_context(
        self,
        *,
        messages: List[Dict[str, Any]],
        request_context: Optional[Dict[str, Any]] = None,
        integrated_context: Optional[Dict[str, Any]] = None,
        profile: Optional[Dict[str, Any]] = None,
        workflow_context: Optional[Dict[str, Any]] = None,
        cortex_intent: Optional[Dict[str, Any]] = None,
        token_budget: int = 4096,
        prompt_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> PromptAssemblyRequest:
        """Normalize trusted runtime context into the canonical prompt contract.

        Domain owners retain ranking authority. This method does not score or
        invent context; it preserves supplied order, deduplicates exact repeats,
        and maps each domain into an existing PromptAssemblyRequest field.
        """

        request_context = dict(request_context or {})
        integrated_context = dict(integrated_context or {})
        profile_payload = dict(profile or {})

        for key in ("user_facts", "project_facts"):
            items = self._normalize_context_items(request_context.get(key), source=key)
            if items:
                profile_payload[key] = items

        memory_items: List[Dict[str, Any]] = []
        for key in ("episodic_items", "semantic_long_term_items", "recalled_items"):
            memory_items.extend(
                self._normalize_context_items(request_context.get(key), source=key)
            )
        memory_items.extend(
            self._normalize_context_items(integrated_context.get("memories"), source="memory")
        )
        memory_items.extend(
            self._normalize_context_items(integrated_context.get("recall"), source="recall")
        )
        memory_items = self._dedupe_context_items(memory_items)

        instruction_lines = self._instruction_lines(integrated_context.get("instructions"))

        return PromptAssemblyRequest(
            system_instructions="\n".join(instruction_lines),
            profile=profile_payload,
            memory_items=memory_items,
            cortex_intent=dict(cortex_intent or {}),
            workflow_context=dict(workflow_context or {}),
            token_budget=max(1, int(token_budget or 4096)),
            messages=[dict(message) for message in messages],
            prompt_id=prompt_id,
            prompt_version=prompt_version,
        )

    def render_text_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """Render canonical assembled messages for plain-text provider transports."""

        return self.assembler.render_text_prompt(messages)

    @staticmethod
    def _normalize_context_items(value: Any, *, source: str) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(value):
            if isinstance(item, dict):
                content = str(item.get("content") or item.get("text") or "").strip()
                if not content:
                    continue
                normalized_item = dict(item)
                normalized_item.setdefault("id", f"{source}-{index}")
                normalized_item.setdefault("source", source)
                normalized_item["content"] = content
                normalized.append(normalized_item)
            elif item is not None:
                content = str(item).strip()
                if content:
                    normalized.append(
                        {"id": f"{source}-{index}", "source": source, "content": content}
                    )
        return normalized

    @staticmethod
    def _dedupe_context_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        deduped: List[Dict[str, Any]] = []
        for item in items:
            key = (str(item.get("id") or ""), str(item.get("content") or "").strip())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _instruction_lines(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        lines: List[str] = []
        for item in value:
            if isinstance(item, dict):
                content = str(item.get("content") or item.get("text") or "").strip()
            else:
                content = str(item or "").strip()
            if content and content not in lines:
                lines.append(content)
        return lines

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
