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

from ai_karen_engine.core.runtime.contracts import ExecutionBudget
from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptDefinition,
    PromptTruncationEvent,
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


class PromptAssemblyError(Exception):
    """Raised when prompt assembly cannot complete due to budget or resolution failure."""


class PromptAssembler:
    """Assembles canonical prompts from trusted runtime components."""

    def __init__(self, registry: Optional[PromptRegistry] = None) -> None:
        self.registry = registry or get_prompt_registry()

    async def assemble(self, request: PromptAssemblyRequest) -> PromptAssemblyResult:
        """Assemble prompt from request inputs."""
        prompt_definition = self._resolve_prompt_definition(request)
        if prompt_definition is None and request.prompt_version is not None:
            raise PromptAssemblyError(
                f"PromptDefinition not found: {request.prompt_id}@{request.prompt_version}"
            )

        effective_request = self._apply_prompt_definition(request, prompt_definition)

        budget = self._resolve_budget(effective_request, prompt_definition)
        sections, truncation_events = self._build_sections(effective_request, budget)
        messages, token_estimate = self._assemble_messages(sections, effective_request, budget)

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

    def _resolve_budget(
        self,
        request: PromptAssemblyRequest,
        prompt_definition: Optional[PromptDefinition],
    ) -> ExecutionBudget:
        """Resolve the effective execution budget for prompt assembly."""
        if isinstance(request.token_budget, ExecutionBudget):
            return request.token_budget
        total_budget = request.token_budget or (prompt_definition.token_budget if prompt_definition else 4096)
        max_output = max(1, total_budget // 4)
        max_input = max(0, total_budget - max_output)
        return ExecutionBudget(
            max_input_tokens=max_input,
            max_output_tokens=max_output,
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

        merged_persona = dict(prompt_definition.persona_defaults)
        merged_persona.update(request.persona or {})
        merged_profile = dict(prompt_definition.profile_defaults)
        merged_profile.update(request.profile or {})
        merged_tool_contracts = list(prompt_definition.tool_contracts or [])
        merged_tool_contracts.extend(request.tool_contracts or [])
        merged_output_schema = dict(prompt_definition.output_schema)
        merged_output_schema.update(request.output_schema or {})

        return PromptAssemblyRequest(
            system_policy=request.system_policy,
            tenant_policy=request.tenant_policy,
            system_instructions=request.system_instructions or prompt_definition.system_instructions,
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
        budget: ExecutionBudget,
    ) -> Tuple[List[Tuple[str, str, int]], List[PromptTruncationEvent]]:
        """Build ordered prompt sections with token estimates."""
        sections: List[Tuple[str, str, int]] = []
        truncation_events: List[PromptTruncationEvent] = []

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

        profile_blocks = self._build_profile_blocks(request)
        if profile_blocks:
            content = "\n".join(profile_blocks)
            sections.append(("profile", content, self._estimate_tokens(content)))

        provider_capability_blocks = self._build_provider_capability_blocks(request)
        if provider_capability_blocks:
            content = "\n".join(provider_capability_blocks)
            sections.append(("provider_capabilities", content, self._estimate_tokens(content)))

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

        available_budget = budget.max_input_tokens
        truncated_sections, truncation_events = self._enforce_token_budget(sections, available_budget)

        return truncated_sections, truncation_events

    def _assemble_messages(
        self,
        sections: List[Tuple[str, str, int]],
        request: PromptAssemblyRequest,
        budget: ExecutionBudget,
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

            if total_tokens + estimated_tokens > budget.max_input_tokens:
                break
            messages.append({"role": "system", "content": content})
            total_tokens += estimated_tokens

        for msg in request.messages:
            messages.append(dict(msg))
            total_tokens += self._estimate_tokens(str(msg.get("content", "")))

        return messages, total_tokens

    def _enforce_token_budget(
        self,
        sections: List[Tuple[str, str, int]],
        available_budget: int,
    ) -> Tuple[List[Tuple[str, str, int]], List[PromptTruncationEvent]]:
        """Truncate lower-priority sections to fit within token budget."""
        protected = {"system", "output", "user"}
        truncation_order = ["tool", "workflow", "memory", "profile", "provider_capabilities", "cortex", "persona"]

        total = sum(tokens for _, _, tokens in sections)
        truncated = list(sections)
        events: List[PromptTruncationEvent] = []

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
                events.append(PromptTruncationEvent(
                    section=role,
                    reason="token_budget",
                    original_tokens=tokens,
                    remaining_tokens=max(0, available_budget - total),
                    items_removed=1,
                ))
                total -= tokens
                if total <= available_budget:
                    break

        remaining_total = sum(tokens for _, _, tokens in truncated)
        if remaining_total > available_budget:
            protected_sections = [s for s in truncated if s[0] in protected]
            if protected_sections:
                raise PromptAssemblyError(
                    f"Protected prompt sections exceed available token budget. "
                    f"Required={remaining_total}, available={available_budget}. "
                    f"Sections={[s[0] for s in protected_sections]}"
                )

        return truncated, events

    def _build_system_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        blocks = []
        if request.system_policy:
            blocks.append(request.system_policy)
        if request.tenant_policy:
            blocks.append(request.tenant_policy)
        if request.system_instructions:
            blocks.append(request.system_instructions)
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

    def _build_profile_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        if not request.profile:
            return []
        blocks = []
        for key, value in request.profile.items():
            blocks.append(f"Profile: {key}={value}")
        return blocks

    def _build_provider_capability_blocks(self, request: PromptAssemblyRequest) -> List[str]:
        if not request.provider_capabilities:
            return []
        blocks = []
        for key, value in request.provider_capabilities.items():
            blocks.append(f"{key}={value}")
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
        if not _prompt_assembler.registry.list_definitions():
            register_default_prompts(_prompt_assembler.registry)
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
            system_instructions="You are Karen, a helpful assistant.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.chat.reasoning",
            version="v1",
            name="Karen Chat Reasoning",
            description="Reasoning-optimized chat prompt contract",
            system_instructions="You are Karen. Think step by step before answering.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.workflow.default",
            version="v1",
            name="Workflow Default",
            description="Default workflow prompt contract",
            system_instructions="You are Karen. Follow the workflow steps carefully.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.tool.use",
            version="v1",
            name="Tool Use",
            description="Tool-use prompt contract",
            system_instructions="You are Karen. Use available tools when needed.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.extension.default",
            version="v1",
            name="Extension Default",
            description="Default extension prompt contract",
            system_instructions="You are Karen. Integrate extension outputs safely.",
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.agent.analyst.intent",
            version="v1",
            name="Analyst Intent",
            description="Analyst specialist intent-classification and query-structuring prompt",
            system_instructions=(
                "Analyze the following user query for Karen AI. "
                "Detect the primary intent (e.g., weather, information, task) and extract key terms.\n\n"
                "User Query: {query}\n\n"
                "Respond with a JSON object:\n"
                "{{\n  \"intent\": \"string\",\n  \"key_terms\": [\"list\", \"of\", \"terms\"],\n  \"requires_research\": boolean\n}}"
            ),
            token_budget=4096,
        ),
        PromptDefinition(
            prompt_id="karen.agent.researcher.synthesis",
            version="v1",
            name="Researcher Synthesis",
            description="Researcher specialist findings-synthesis prompt",
            system_instructions=(
                "As a Researcher Agent, summarize the following tool findings for the query: \"{query}\"\n\n"
                "Findings:\n{findings}"
            ),
            token_budget=4096,
        ),
    ]
    for definition in defaults:
        target.register(definition)
    return target
