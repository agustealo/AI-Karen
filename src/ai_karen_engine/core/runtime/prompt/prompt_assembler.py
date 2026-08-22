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

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptDefinition,
)

logger = logging.getLogger(__name__)


class PromptRegistry:
    """Registry of known prompt definitions."""

    def __init__(self) -> None:
        self._definitions: Dict[str, PromptDefinition] = {}

    def _key(self, prompt_id: str, version: str) -> str:
        return f"{prompt_id}@{version}"

    def register(self, definition: PromptDefinition) -> None:
        self._definitions[self._key(definition.prompt_id, definition.version)] = definition

    def get(self, prompt_id: str, version: Optional[str] = None) -> Optional[PromptDefinition]:
        if version:
            return self._definitions.get(self._key(prompt_id, version))
        matches = [
            definition
            for key, definition in self._definitions.items()
            if key.startswith(f"{prompt_id}@")
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.version)[-1]

    def list_definitions(self) -> List[PromptDefinition]:
        return list(self._definitions.values())


_PROMPT_REGISTRY_INSTANCE: Optional[PromptRegistry] = None


def get_prompt_registry() -> PromptRegistry:
    """Return the global PromptRegistry instance."""
    global _PROMPT_REGISTRY_INSTANCE
    if _PROMPT_REGISTRY_INSTANCE is None:
        _PROMPT_REGISTRY_INSTANCE = PromptRegistry()
    return _PROMPT_REGISTRY_INSTANCE


class PromptAssembler:
    """Assembles canonical prompts from trusted runtime components."""

    def __init__(self, registry: Optional[PromptRegistry] = None) -> None:
        self.registry = registry or get_prompt_registry()

    async def assemble(self, request: PromptAssemblyRequest) -> PromptAssemblyResult:
        """Assemble prompt from request inputs."""
        prompt_definition = self._resolve_prompt_definition(request)
        effective_request = self._apply_prompt_definition(request, prompt_definition)

        token_budget = effective_request.token_budget or (prompt_definition.token_budget if prompt_definition else 4096)
        sections, truncation_events = self._build_sections(effective_request, token_budget)
        messages, token_estimate = self._assemble_messages(sections, effective_request, token_budget)

        prompt_hash = hashlib.sha256(
            str({
                "messages": messages,
                "prompt_id": effective_request.prompt_id,
                "version": effective_request.prompt_version,
            }).encode("utf-8")
        ).hexdigest()[:16]

        included_memory_refs = [
            item.get("id") or item.get("memory_id")
            for item in effective_request.memory_items[:3]
            if item.get("id") or item.get("memory_id")
        ]
        included_tool_contracts = [
            contract.get("name") or contract.get("tool_id")
            for contract in effective_request.tool_contracts
            if contract.get("name") or contract.get("tool_id")
        ]

        return PromptAssemblyResult(
            messages=messages,
            prompt_id=effective_request.prompt_id or "karen.chat.default",
            prompt_version=effective_request.prompt_version or "v1",
            prompt_hash=prompt_hash,
            included_memory_refs=included_memory_refs,
            included_tool_contracts=included_tool_contracts,
            token_estimate=token_estimate,
            truncation_events=truncation_events,
            metadata={
                "registry_lookup": prompt_definition is not None,
                "prompt_contract_id": prompt_definition.prompt_id if prompt_definition else None,
                "memory_items_considered": len(effective_request.memory_items),
                "tool_contracts_considered": len(effective_request.tool_contracts),
            },
        )

    def _resolve_prompt_definition(self, request: PromptAssemblyRequest) -> Optional[PromptDefinition]:
        """Resolve the best matching PromptDefinition from the registry."""
        prompt_id = request.prompt_id
        version = request.prompt_version
        if not prompt_id:
            return None
        if version:
            return self.registry.get(prompt_id, version)
        return self.registry.get(prompt_id)

    def _apply_prompt_definition(
        self,
        request: PromptAssemblyRequest,
        prompt_definition: Optional[PromptDefinition],
    ) -> PromptAssemblyRequest:
        """Merge request with resolved PromptDefinition defaults."""
        if not prompt_definition:
            return request

        merged_system_policy = prompt_definition.system_policy or request.system_policy
        merged_tenant_policy = prompt_definition.tenant_policy or request.tenant_policy
        merged_persona = dict(prompt_definition.persona)
        merged_persona.update(request.persona or {})
        merged_profile = dict(prompt_definition.profile)
        merged_profile.update(request.profile or {})
        merged_tool_contracts = list(prompt_definition.tool_contracts or [])
        merged_tool_contracts.extend(request.tool_contracts or [])
        merged_output_schema = dict(prompt_definition.output_schema)
        merged_output_schema.update(request.output_schema or {})

        return PromptAssemblyRequest(
            system_policy=request.system_policy or merged_system_policy,
            tenant_policy=request.tenant_policy or merged_tenant_policy,
            persona=merged_persona,
            profile=merged_profile,
            memory_items=request.memory_items,
            cortex_intent=request.cortex_intent,
            tool_contracts=merged_tool_contracts,
            workflow_context=request.workflow_context,
            provider_capabilities=request.provider_capabilities,
            token_budget=request.token_budget or prompt_definition.token_budget,
            output_schema=merged_output_schema,
            messages=request.messages,
            prompt_id=request.prompt_id or prompt_definition.prompt_id,
            prompt_version=request.prompt_version or prompt_definition.version,
        )

    def _build_sections(
        self,
        request: PromptAssemblyRequest,
        token_budget: int,
    ) -> Tuple[List[Tuple[str, str, int]], List[str]]:
        """Build ordered prompt sections with token estimates."""
        sections: List[Tuple[str, str, int]] = []
        truncation_events: List[str] = []

        system_blocks = self._build_system_blocks(request)
        if system_blocks:
            content = "\n".join(system_blocks)
            sections.append(("system", content, self._estimate_tokens(content)))

        persona_blocks = self._build_persona_blocks(request)
        if persona_blocks:
            content = "\n".join(persona_blocks)
            sections.append(("persona", content, self._estimate_tokens(content)))

        cortex_blocks = self._build_cortex_blocks(request)
        if cortex_blocks:
            content = "\n".join(cortex_blocks)
            sections.append(("cortex", content, self._estimate_tokens(content)))

        memory_blocks, memory_refs = self._build_memory_blocks(request)
        if memory_blocks:
            content = "\n".join(memory_blocks)
            sections.append(("memory", content, self._estimate_tokens(content)))

        tool_blocks, tool_refs = self._build_tool_blocks(request)
        if tool_blocks:
            content = "\n".join(tool_blocks)
            sections.append(("tool", content, self._estimate_tokens(content)))

        workflow_blocks = self._build_workflow_blocks(request)
        if workflow_blocks:
            content = "\n".join(workflow_blocks)
            sections.append(("workflow", content, self._estimate_tokens(content)))

        output_blocks = self._build_output_blocks(request)
        if output_blocks:
            content = "\n".join(output_blocks)
            sections.append(("output", content, self._estimate_tokens(content)))

        user_blocks = self._build_user_blocks(request)
        if user_blocks:
            content = "\n".join(user_blocks)
            sections.append(("user", content, self._estimate_tokens(content)))

        reserved_output_tokens = 1024
        available_budget = max(0, token_budget - reserved_output_tokens)
        truncated_sections, truncation_events = self._enforce_token_budget(sections, available_budget)

        return truncated_sections, truncation_events

    def _assemble_messages(
        self,
        sections: List[Tuple[str, str, int]],
        request: PromptAssemblyRequest,
        token_budget: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Convert ordered sections into provider messages."""
        messages: List[Dict[str, Any]] = []
        total_tokens = 0

        protected_roles = {"system", "output"}
        for role, content, estimated_tokens in sections:
            if role in protected_roles:
                messages.append({"role": "system", "content": content})
                total_tokens += estimated_tokens
                continue

            if total_tokens + estimated_tokens > token_budget:
                break
            messages.append({"role": "system", "content": content})
            total_tokens += estimated_tokens

        for msg in request.messages:
            messages.append(dict(msg))

        return messages, total_tokens

    def _enforce_token_budget(
        self,
        sections: List[Tuple[str, str, int]],
        available_budget: int,
    ) -> Tuple[List[Tuple[str, str, int]], List[str]]:
        """Truncate lower-priority sections to fit within token budget."""
        protected = {"system", "output", "user"}
        truncation_order = ["tool", "workflow", "memory", "cortex", "persona"]

        total = sum(tokens for _, _, tokens in sections)
        truncated = list(sections)
        events: List[str] = []

        if total <= available_budget:
            return truncated, events

        for section_role in truncation_order:
            if total <= available_budget:
                break
            for index in range(len(truncated) - 1, -1, -1):
                role, content, tokens = truncated[index]
                if role != section_role or role in protected:
                    continue
                truncated.pop(index)
                events.append(f"truncated_{role}")
                total -= tokens
                if total <= available_budget:
                    break

        return truncated, events

    def _build_system_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        blocks = []
        if request.system_policy:
            blocks.append(request.system_policy)
        if request.tenant_policy:
            blocks.append(request.tenant_policy)
        return blocks

    def _build_persona_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        blocks = []
        persona = request.persona or {}
        if persona.get("system_prompt"):
            blocks.append(persona["system_prompt"])
        if persona.get("specialized_instructions"):
            blocks.append(persona["specialized_instructions"])
        return blocks

    def _build_cortex_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        if not request.cortex_intent:
            return []
        blocks = []
        intent = request.cortex_intent.get("intent")
        confidence = request.cortex_intent.get("intent_confidence")
        if intent:
            blocks.append(f"Execution context: intent={intent}, confidence={confidence}")
        return blocks

    def _build_memory_blocks(self, request: PromptAssemblyRequest) -> tuple[List[str], List[str]]:
        if not request.memory_items:
            return [], []

        blocks = []
        refs = []
        lines = ["Relevant context from memory (use only if helpful):"]
        for item in request.memory_items[:3]:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            item_id = str(item.get("id") or item.get("memory_id") or "")
            lines.append(f"[Memory: {content}]")
            if item_id:
                refs.append(item_id)

        if len(lines) > 1:
            blocks.append("\n".join(lines))
        return blocks, refs

    def _build_tool_blocks(self, request: PromptAssemblyRequest) -> tuple[List[str], List[str]]:
        if not request.tool_contracts:
            return [], []

        blocks = []
        refs = []
        lines = ["Available tools:"]
        for contract in request.tool_contracts:
            name = contract.get("name") or contract.get("tool_id") or ""
            description = contract.get("description") or ""
            if name:
                lines.append(f"- {name}: {description}")
                refs.append(name)

        if len(lines) > 1:
            blocks.append("\n".join(lines))
        return blocks, refs

    def _build_workflow_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        if not request.workflow_context:
            return []

        workflow = request.workflow_context
        lines = ["Workflow context:"]
        if workflow.get("workflow_id"):
            lines.append(f"workflow_id={workflow['workflow_id']}")
        if workflow.get("workflow_version"):
            lines.append(f"version={workflow['workflow_version']}")
        if workflow.get("objective"):
            lines.append(f"objective={workflow['objective']}")
        if workflow.get("constraints"):
            constraints = workflow["constraints"]
            if isinstance(constraints, dict):
                for key, value in constraints.items():
                    lines.append(f"constraint.{key}={value}")
        return ["\n".join(lines)] if len(lines) > 1 else []

    def _build_output_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        if not request.output_schema:
            return []
        lines = ["Output contract:"]
        for key, value in request.output_schema.items():
            lines.append(f"{key}={value}")
        return ["\n".join(lines)] if len(lines) > 1 else []

    def _build_user_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        blocks = []
        for msg in request.messages:
            role = str(msg.get("role", "")).lower()
            if role == "user":
                content = str(msg.get("content", "")).strip()
                if content:
                    blocks.append(content)
        return blocks

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count from text length.

        Uses a simple heuristic until a real tokenizer is wired in.
        """
        if not text:
            return 0
        return max(1, len(text) // 4)


_prompt_assembler: Optional[PromptAssembler] = None


def get_prompt_assembler() -> PromptAssembler:
    global _prompt_assembler
    if _prompt_assembler is None:
        _prompt_assembler = PromptAssembler()
    return _prompt_assembler


def register_default_prompts(registry: Optional[PromptRegistry] = None) -> PromptRegistry:
    """Register canonical prompt contracts into the given or global PromptRegistry."""
    target = registry or get_prompt_registry()
    defaults = [
        PromptDefinition(
            prompt_id="karen.chat.default",
            version="v1",
            name="Karen Chat Default",
            description="Default chat prompt contract",
            system_prompt="You are Karen, a helpful assistant.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.chat.reasoning",
            version="v1",
            name="Karen Chat Reasoning",
            description="Reasoning-optimized chat prompt contract",
            system_prompt="You are Karen. Think step by step before answering.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.workflow.default",
            version="v1",
            name="Workflow Default",
            description="Default workflow prompt contract",
            system_prompt="You are Karen. Follow the workflow steps carefully.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.tool.use",
            version="v1",
            name="Tool Use",
            description="Tool-use prompt contract",
            system_prompt="You are Karen. Use available tools when needed.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.extension.default",
            version="v1",
            name="Extension Default",
            description="Default extension prompt contract",
            system_prompt="You are Karen. Integrate extension outputs safely.",
            token_budget=4096,
        ),
    ]
    for definition in defaults:
        target.register(definition)
    return target
