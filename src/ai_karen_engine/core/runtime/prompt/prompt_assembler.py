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
from typing import Any, Dict, List, Optional

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
        messages: List[Dict[str, Any]] = []
        included_memory_refs: List[str] = []
        included_tool_contracts: List[str] = []
        truncation_events: List[str] = []
        token_estimate = 0

        system_blocks = self._build_system_blocks(request)
        if system_blocks:
            messages.append({"role": "system", "content": "\n".join(system_blocks)})

        persona_blocks = self._build_persona_blocks(request)
        if persona_blocks:
            messages.append({"role": "system", "content": "\n".join(persona_blocks)})

        memory_blocks, memory_refs = self._build_memory_blocks(request)
        if memory_blocks:
            messages.append({"role": "system", "content": "\n".join(memory_blocks)})
            included_memory_refs.extend(memory_refs)

        tool_blocks, tool_refs = self._build_tool_blocks(request)
        if tool_blocks:
            messages.append({"role": "system", "content": "\n".join(tool_blocks)})
            included_tool_contracts.extend(tool_refs)

        workflow_blocks = self._build_workflow_blocks(request)
        if workflow_blocks:
            messages.append({"role": "system", "content": "\n".join(workflow_blocks)})

        for msg in request.messages:
            messages.append(dict(msg))

        prompt_hash = hashlib.sha256(
            str({
                "messages": messages,
                "prompt_id": request.prompt_id,
                "version": request.prompt_version,
            }).encode("utf-8")
        ).hexdigest()[:16]

        return PromptAssemblyResult(
            messages=messages,
            prompt_id=request.prompt_id or "karen.chat.default",
            prompt_version=request.prompt_version or "v1",
            prompt_hash=prompt_hash,
            included_memory_refs=included_memory_refs,
            included_tool_contracts=included_tool_contracts,
            token_estimate=token_estimate,
            truncation_events=truncation_events,
            metadata={
                "registry_lookup": bool(request.prompt_id and self.registry.get(request.prompt_id, request.prompt_version)),
                "memory_items_considered": len(request.memory_items),
                "tool_contracts_considered": len(request.tool_contracts),
            },
        )

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
