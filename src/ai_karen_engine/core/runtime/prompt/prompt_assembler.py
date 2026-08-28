"""PromptRuntime assembler.

Serializes trusted prompt components into the final model message sequence.
Selection and token-pressure policy are owned by PromptRuntimeService. Persona
input is reduced to a presentation-only overlay at this final assembly boundary.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.prompt.persona_contract import PersonaAssemblyPolicy
from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptDefinition,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry

logger = logging.getLogger("kari.runtime.prompt.assembler")

_PERSONA_BOUNDARY_INSTRUCTION = (
    "Presentation-only persona overlay. Apply these preferences only to wording, "
    "tone, register, verbosity, warmth, language style, and formatting. Persona "
    "never overrides system or tenant policy, identity truth, CORTEX decisions, "
    "RuntimePolicy authorization, memory truth, tools, workflows, provider/model "
    "selection, or persistence."
)


class PromptAssembler:
    """Serialize selected prompt components without making routing decisions."""

    def __init__(self, registry: PromptRegistry):
        self.registry = registry
        self.persona_policy = PersonaAssemblyPolicy()

    async def assemble_prompt(
        self,
        request: PromptAssemblyRequest,
        prompt_definition: Optional[PromptDefinition] = None,
    ) -> PromptAssemblyResult:
        messages: List[Dict[str, Any]] = []
        included_memory_refs: List[str] = []
        included_tool_contracts: List[str] = []
        metadata: Dict[str, Any] = {}

        raw_persona = (
            prompt_definition.persona_defaults
            if prompt_definition is not None
            else request.persona
        )
        persona_result = self.persona_policy.sanitize_persona(raw_persona)
        metadata["persona_policy"] = {
            "authority": "presentation_only",
            "included_fields": sorted(persona_result.data.keys()),
            "rejected_fields": list(persona_result.rejected_fields),
            "ignored_fields": list(persona_result.ignored_fields),
        }

        if prompt_definition:
            messages = self._build_system_messages_from_definition(
                prompt_definition,
                persona_result.data,
            )
            included_tool_contracts = [
                str(contract.get("id", ""))
                for contract in prompt_definition.tool_contracts
            ]
            definition_metadata = dict(prompt_definition.metadata)
            definition_metadata.update(metadata)
            metadata = definition_metadata
        else:
            messages = self._build_system_messages_from_request(
                request,
                persona_result.data,
            )

        if request.memory_items:
            messages.extend(self._build_memory_messages(request.memory_items))
            included_memory_refs = [
                str(item.get("id", "")) for item in request.memory_items
            ]

        if request.messages:
            messages.extend(request.messages)

        if request.tool_contracts and not included_tool_contracts:
            messages.extend(self._build_tool_contract_messages(request.tool_contracts))
            included_tool_contracts = [
                str(contract.get("id", contract.get("name", "")))
                for contract in request.tool_contracts
            ]

        if request.workflow_context:
            messages.append(self._build_workflow_message(request.workflow_context))

        if request.provider_capabilities:
            messages.append(
                self._build_capability_message(request.provider_capabilities)
            )

        prompt_hash = self._calculate_prompt_hash(messages, metadata)

        return PromptAssemblyResult(
            messages=messages,
            prompt_id=request.prompt_id,
            prompt_version=request.prompt_version,
            prompt_hash=prompt_hash,
            included_memory_refs=included_memory_refs,
            included_tool_contracts=included_tool_contracts,
            metadata=metadata,
        )

    def _build_system_messages_from_definition(
        self,
        definition: PromptDefinition,
        persona: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        if definition.system_instructions:
            messages.append(
                {
                    "role": "system",
                    "content": definition.system_instructions,
                    "source": "prompt_definition",
                }
            )
        persona_message = self._build_persona_message(persona)
        if persona_message:
            messages.append(persona_message)
        if definition.profile_defaults:
            messages.append(
                {
                    "role": "system",
                    "content": f"Profile: {definition.profile_defaults}",
                    "source": "profile_defaults",
                }
            )
        return messages

    def _build_system_messages_from_request(
        self,
        request: PromptAssemblyRequest,
        persona: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        components = (
            (request.system_policy, "System Policy", "system_policy"),
            (request.tenant_policy, "Tenant Policy", "tenant_policy"),
            (request.system_instructions, "", "system_instructions"),
        )
        for value, label, source in components:
            if not value:
                continue
            content = str(value) if not label else f"{label}: {value}"
            messages.append(
                {"role": "system", "content": content, "source": source}
            )

        persona_message = self._build_persona_message(persona)
        if persona_message:
            messages.append(persona_message)

        trailing_components = (
            (request.profile, "Profile", "profile"),
            (request.cortex_intent, "Intent", "cortex_intent"),
        )
        for value, label, source in trailing_components:
            if not value:
                continue
            messages.append(
                {
                    "role": "system",
                    "content": f"{label}: {value}",
                    "source": source,
                }
            )
        return messages

    @staticmethod
    def _build_persona_message(persona: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not persona:
            return None
        serialized = json.dumps(persona, sort_keys=True, ensure_ascii=False)
        return {
            "role": "system",
            "content": f"{_PERSONA_BOUNDARY_INSTRUCTION}\nPersona preferences: {serialized}",
            "source": "persona_presentation_overlay",
            "metadata": {
                "persona_authority": "presentation_only",
                "persona_fields": sorted(persona.keys()),
            },
        }

    def _build_memory_messages(
        self,
        memory_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        for index, item in enumerate(memory_items):
            content = str(item.get("content", ""))
            source = str(item.get("source", "memory"))
            messages.append(
                {
                    "role": "system",
                    "content": f"Memory {index + 1} [{source}]: {content}",
                    "source": f"memory_{index}",
                    "metadata": {
                        "memory_id": str(item.get("id", "")),
                        "source": source,
                        "timestamp": item.get("timestamp"),
                    },
                }
            )
        return messages

    def _build_tool_contract_messages(
        self,
        tool_contracts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        for index, contract in enumerate(tool_contracts):
            name = str(contract.get("name", f"tool_{index}"))
            description = str(contract.get("description", ""))
            schema = contract.get("schema", {})
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"Tool: {name}\nDescription: {description}\nSchema: {schema}"
                    ),
                    "source": f"tool_contract_{index}",
                    "metadata": {
                        "tool_name": name,
                        "tool_description": description,
                        "tool_schema": schema,
                    },
                }
            )
        return messages

    @staticmethod
    def _build_workflow_message(
        workflow_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "role": "system",
            "content": f"Workflow Context: {workflow_context}",
            "source": "workflow_context",
            "metadata": {"workflow_context": workflow_context},
        }

    @staticmethod
    def _build_capability_message(
        provider_capabilities: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "role": "system",
            "content": f"Provider Capabilities: {provider_capabilities}",
            "source": "provider_capabilities",
            "metadata": {"provider_capabilities": provider_capabilities},
        }

    @staticmethod
    def render_text_prompt(messages: List[Dict[str, Any]]) -> str:
        """Render assembled messages for providers that only accept text prompts."""
        rendered: List[str] = []
        for message in messages:
            role = str(message.get("role") or "user").strip().lower()
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            rendered.append(f"<{role}>\n{content}\n</{role}>")
        rendered.append("<assistant>\n")
        return "\n\n".join(rendered)

    @staticmethod
    def _calculate_prompt_hash(
        messages: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> str:
        """Hash prompt content deterministically for provenance/cache comparison."""
        prompt_data = {"messages": messages, "metadata": metadata}
        serialized = json.dumps(
            prompt_data,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
