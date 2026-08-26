"""
PromptRuntime assembler.

Assembles prompts from various components with versioning and budgeting.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptDefinition,
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptTruncationEvent,
    PromptVersion,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry

logger = logging.getLogger("kari.runtime.prompt.assembler")


class PromptAssembler:
    """Assembles prompts from request components."""
    
    def __init__(self, registry: PromptRegistry):
        self.registry = registry
    
    async def assemble_prompt(
        self,
        request: PromptAssemblyRequest,
        prompt_definition: Optional[PromptDefinition] = None
    ) -> PromptAssemblyResult:
        """Assemble a prompt from request components."""
        
        messages = []
        included_memory_refs = []
        included_tool_contracts = []
        metadata = {}
        
        # Start with system messages
        if prompt_definition:
            # Use prompt definition as base
            messages = self._build_system_messages_from_definition(prompt_definition)
            included_tool_contracts = prompt_definition.tool_contracts
            metadata.update(prompt_definition.metadata)
        else:
            # Build from request
            messages = self._build_system_messages_from_request(request)
            included_tool_contracts = request.tool_contracts
        
        # Add memory context
        if request.memory_items:
            memory_messages = self._build_memory_messages(request.memory_items)
            messages.extend(memory_messages)
            included_memory_refs = [str(item.get("id", "")) for item in request.memory_items]
        
        # Add conversation messages
        if request.messages:
            messages.extend(request.messages)
        
        # Add tool contracts
        if request.tool_contracts and not included_tool_contracts:
            tool_messages = self._build_tool_contract_messages(request.tool_contracts)
            messages.extend(tool_messages)
            included_tool_contracts = [str(contract.get("id", "")) for contract in request.tool_contracts]
        
        # Add workflow context
        if request.workflow_context:
            workflow_message = self._build_workflow_message(request.workflow_context)
            messages.append(workflow_message)
        
        # Add provider capabilities
        if request.provider_capabilities:
            capability_message = self._build_capability_message(request.provider_capabilities)
            messages.append(capability_message)
        
        # Calculate prompt hash for provenance
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
    
    def _build_system_messages_from_definition(self, definition: PromptDefinition) -> List[Dict[str, Any]]:
        """Build system messages from prompt definition."""
        messages = []
        
        # Main system instructions
        if definition.system_instructions:
            messages.append({
                "role": "system",
                "content": definition.system_instructions,
                "source": "prompt_definition"
            })
        
        # Persona defaults
        if definition.persona_defaults:
            persona_message = {
                "role": "system",
                "content": f"Persona: {definition.persona_defaults}",
                "source": "persona_defaults"
            }
            messages.append(persona_message)
        
        # Profile defaults
        if definition.profile_defaults:
            profile_message = {
                "role": "system",
                "content": f"Profile: {definition.profile_defaults}",
                "source": "profile_defaults"
            }
            messages.append(profile_message)
        
        return messages
    
    def _build_system_messages_from_request(self, request: PromptAssemblyRequest) -> List[Dict[str, Any]]:
        """Build system messages from request."""
        messages = []
        
        # System policy
        if request.system_policy:
            messages.append({
                "role": "system",
                "content": f"System Policy: {request.system_policy}",
                "source": "system_policy"
            })
        
        # Tenant policy
        if request.tenant_policy:
            messages.append({
                "role": "system",
                "content": f"Tenant Policy: {request.tenant_policy}",
                "source": "tenant_policy"
            })
        
        # System instructions
        if request.system_instructions:
            messages.append({
                "role": "system",
                "content": request.system_instructions,
                "source": "system_instructions"
            })
        
        # Persona
        if request.persona:
            persona_message = {
                "role": "system",
                "content": f"Persona: {request.persona}",
                "source": "persona"
            }
            messages.append(persona_message)
        
        # Profile
        if request.profile:
            profile_message = {
                "role": "system",
                "content": f"Profile: {request.profile}",
                "source": "profile"
            }
            messages.append(profile_message)
        
        # Cortex intent
        if request.cortex_intent:
            cortex_message = {
                "role": "system",
                "content": f"Intent: {request.cortex_intent}",
                "source": "cortex_intent"
            }
            messages.append(cortex_message)
        
        return messages
    
    def _build_memory_messages(self, memory_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build messages from memory context."""
        messages = []
        
        for i, item in enumerate(memory_items):
            content = str(item.get("content", ""))
            source = str(item.get("source", "memory"))
            timestamp = item.get("timestamp")
            
            message = {
                "role": "system",
                "content": f"Memory {i+1} [{source}]: {content}",
                "source": f"memory_{i}",
                "metadata": {
                    "memory_id": str(item.get("id", "")),
                    "source": source,
                    "timestamp": timestamp,
                }
            }
            
            messages.append(message)
        
        return messages
    
    def _build_tool_contract_messages(self, tool_contracts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build messages from tool contracts."""
        messages = []
        
        for i, contract in enumerate(tool_contracts):
            name = str(contract.get("name", f"tool_{i}"))
            description = str(contract.get("description", ""))
            schema = contract.get("schema", {})
            
            message = {
                "role": "system",
                "content": f"Tool: {name}\nDescription: {description}\nSchema: {schema}",
                "source": f"tool_contract_{i}",
                "metadata": {
                    "tool_name": name,
                    "tool_description": description,
                    "tool_schema": schema,
                }
            }
            
            messages.append(message)
        
        return messages
    
    def _build_workflow_message(self, workflow_context: Dict[str, Any]) -> Dict[str, Any]:
        """Build workflow context message."""
        return {
            "role": "system",
            "content": f"Workflow Context: {workflow_context}",
            "source": "workflow_context",
            "metadata": {
                "workflow_context": workflow_context,
            }
        }
    
    def _build_capability_message(self, provider_capabilities: Dict[str, Any]) -> Dict[str, Any]:
        """Build provider capabilities message."""
        return {
            "role": "system",
            "content": f"Provider Capabilities: {provider_capabilities}",
            "source": "provider_capabilities",
            "metadata": {
                "provider_capabilities": provider_capabilities,
            }
        }
    
    def _calculate_prompt_hash(self, messages: List[Dict[str, Any]], metadata: Dict[str, Any]) -> str:
        """Calculate hash of assembled prompt for provenance."""
        import hashlib
        import json
        
        # Create deterministic representation
        prompt_data = {
            "messages": messages,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Sort keys for deterministic hash
        sorted_data = json.dumps(prompt_data, sort_keys=True)
        return hashlib.sha256(sorted_data.encode()).hexdigest()