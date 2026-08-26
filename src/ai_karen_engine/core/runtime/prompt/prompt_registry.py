"""
PromptRuntime registry and management system.

Provides registry, versioning, and management of prompt definitions.
Supports token budgeting, provenance tracking, and output schema validation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigModel, Field

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptDefinition,
    PromptVersion,
    PromptLifecycleStatus,
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptTruncationEvent,
)

logger = logging.getLogger("kari.runtime.prompt.registry")


class RegistryError(Exception):
    """Base exception for registry operations."""
    pass


class PromptNotFoundError(RegistryError):
    """Raised when prompt is not found."""
    pass


class VersionConflictError(RegistryError):
    """Raised when version conflicts occur."""
    pass


class TokenEstimateError(RegistryError):
    """Raised when token estimation fails."""
    pass


@dataclass
class TokenEstimate:
    """Token estimation result."""
    
    total_tokens: int
    system_tokens: int = 0
    memory_tokens: int = 0
    tool_tokens: int = 0
    message_tokens: int = 0
    overhead_tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "system_tokens": self.system_tokens,
            "memory_tokens": self.memory_tokens,
            "tool_tokens": self.tool_tokens,
            "message_tokens": self.message_tokens,
            "overhead_tokens": self.overhead_tokens,
        }


class PromptRegistry:
    """Registry for prompt definitions with versioning and management."""
    
    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or Path("registry")
        self.registry_path.mkdir(parents=True, exist_ok=True)
        
        self._prompts: Dict[str, PromptDefinition] = {}
        self._version_index: Dict[str, Dict[PromptVersion, str]] = {}
        self._active_versions: Dict[str, PromptVersion] = {}
        
        self._load_registry()
    
    def _load_registry(self):
        """Load prompts from registry storage."""
        registry_file = self.registry_path / "registry.json"
        if not registry_file.exists():
            return
        
        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Load prompts
            for prompt_data in data.get("prompts", []):
                prompt = PromptDefinition(**prompt_data)
                self._prompts[prompt.prompt_id] = prompt
                
                # Index versions
                if prompt.prompt_id not in self._version_index:
                    self._version_index[prompt.prompt_id] = {}
                
                version = prompt.parsed_version
                self._version_index[prompt.prompt_id][version] = prompt.prompt_id
                
                # Track active versions
                if prompt.is_default:
                    self._active_versions[prompt.prompt_id] = version
            
            logger.info(f"Loaded {len(self._prompts)} prompts from registry")
        
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
            raise RegistryError(f"Failed to load registry: {e}")
    
    def _save_registry(self):
        """Save prompts to registry storage."""
        registry_file = self.registry_path / "registry.json"
        
        try:
            data = {
                "prompts": [prompt.__dict__ for prompt in self._prompts.values()],
                "active_versions": {pid: str(version) for pid, version in self._active_versions.items()},
                "updated_at": datetime.utcnow().isoformat(),
            }
            
            with open(registry_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.debug("Registry saved successfully")
        
        except Exception as e:
            logger.error(f"Failed to save registry: {e}")
            raise RegistryError(f"Failed to save registry: {e}")
    
    def register_prompt(self, prompt: PromptDefinition) -> PromptDefinition:
        """Register a new prompt definition."""
        
        # Validate prompt
        self._validate_prompt(prompt)
        
        # Check for version conflicts
        if prompt.prompt_id in self._version_index:
            existing_versions = self._version_index[prompt.prompt_id]
            new_version = prompt.parsed_version
            
            if new_version in existing_versions:
                raise VersionConflictError(f"Version {new_version} already exists for prompt {prompt.prompt_id}")
        
        # Add to registry
        self._prompts[prompt.prompt_id] = prompt
        
        # Update version index
        if prompt.prompt_id not in self._version_index:
            self._version_index[prompt.prompt_id] = {}
        
        self._version_index[prompt.prompt_id][prompt.parsed_version] = prompt.prompt_id
        
        # Set as active if marked as default
        if prompt.is_default:
            self._active_versions[prompt.prompt_id] = prompt.parsed_version
        
        # Save registry
        self._save_registry()
        
        logger.info(f"Registered prompt: {prompt.prompt_id} v{prompt.version}")
        return prompt
    
    def get_prompt(self, prompt_id: str, version: Optional[str] = None) -> PromptDefinition:
        """Get a prompt definition by ID and optional version."""
        
        if prompt_id not in self._prompts:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")
        
        if version is None:
            # Get active version
            if prompt_id in self._active_versions:
                active_version = self._active_versions[prompt_id]
                return self._prompts[prompt_id]
            else:
                # Get the latest version
                versions = self._version_index[prompt_id]
                if versions:
                    latest_version = max(versions.keys())
                    return self._prompts[versions[latest_version]]
                else:
                    raise PromptNotFoundError(f"No versions found for prompt {prompt_id}")
        else:
            # Get specific version
            parsed_version = PromptVersion.parse(version)
            if prompt_id in self._version_index and parsed_version in self._version_index[prompt_id]:
                prompt_id_key = self._version_index[prompt_id][parsed_version]
                return self._prompts[prompt_id_key]
            else:
                raise PromptNotFoundError(f"Version {version} not found for prompt {prompt_id}")
    
    def list_prompts(self) -> List[PromptDefinition]:
        """List all prompt definitions."""
        return list(self._prompts.values())
    
    def list_versions(self, prompt_id: str) -> List[PromptVersion]:
        """List all versions for a prompt."""
        if prompt_id not in self._version_index:
            return []
        
        return list(self._version_index[prompt_id].keys())
    
    def set_active_version(self, prompt_id: str, version: str) -> bool:
        """Set the active version for a prompt."""
        
        if prompt_id not in self._prompts:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")
        
        parsed_version = PromptVersion.parse(version)
        if prompt_id not in self._version_index or parsed_version not in self._version_index[prompt_id]:
            raise PromptNotFoundError(f"Version {version} not found for prompt {prompt_id}")
        
        # Update active version
        self._active_versions[prompt_id] = parsed_version
        
        # Update prompt's is_default flag
        for prompt in self._prompts.values():
            if prompt.prompt_id == prompt_id:
                prompt.is_default = (prompt.parsed_version == parsed_version)
                break
        
        # Save registry
        self._save_registry()
        
        logger.info(f"Set active version for {prompt_id}: {version}")
        return True
    
    def retire_prompt(self, prompt_id: str, version: Optional[str] = None) -> bool:
        """Retire a prompt or version."""
        
        if prompt_id not in self._prompts:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")
        
        if version is None:
            # Retire entire prompt
            del self._prompts[prompt_id]
            self._version_index.pop(prompt_id, None)
            self._active_versions.pop(prompt_id, None)
            logger.info(f"Retired prompt: {prompt_id}")
        else:
            # Retire specific version
            parsed_version = PromptVersion.parse(version)
            if prompt_id in self._version_index and parsed_version in self._version_index[prompt_id]:
                del self._version_index[prompt_id][parsed_version]
                
                # Update active version if this was the active one
                if prompt_id in self._active_versions and self._active_versions[prompt_id] == parsed_version:
                    # Find next best version
                    remaining_versions = self._version_index[prompt_id]
                    if remaining_versions:
                        self._active_versions[prompt_id] = max(remaining_versions.keys())
                    else:
                        del self._active_versions[prompt_id]
                
                logger.info(f"Retired prompt version: {prompt_id} {version}")
            else:
                raise PromptNotFoundError(f"Version {version} not found for prompt {prompt_id}")
        
        # Save registry
        self._save_registry()
        
        return True
    
    def _validate_prompt(self, prompt: PromptDefinition):
        """Validate a prompt definition."""
        
        if not prompt.prompt_id:
            raise ValueError("prompt_id is required")
        
        if not prompt.version:
            raise ValueError("version is required")
        
        if not prompt.name:
            prompt.name = prompt.prompt_id
        
        # Validate version format
        try:
            PromptVersion.parse(prompt.version)
        except ValueError as e:
            raise ValueError(f"Invalid version format: {e}")
        
        # Validate token budget
        if prompt.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        
        # Validate output schema if present
        if prompt.output_schema:
            self._validate_schema(prompt.output_schema)
    
    def _validate_schema(self, schema: Dict[str, Any]):
        """Validate JSON schema."""
        # Basic schema validation - could be enhanced with jsonschema library
        if not isinstance(schema, dict):
            raise ValueError("output_schema must be a dictionary")
        
        if "type" not in schema:
            raise ValueError("output_schema must have a 'type' field")
    
    def estimate_tokens(self, request: PromptAssemblyRequest) -> TokenEstimate:
        """Estimate token count for a prompt assembly request."""
        
        total_tokens = 0
        breakdown = TokenEstimate()
        
        try:
            # System policy tokens
            if request.system_policy:
                breakdown.system_tokens += self._count_tokens(request.system_policy)
            
            # Tenant policy tokens
            if request.tenant_policy:
                breakdown.system_tokens += self._count_tokens(request.tenant_policy)
            
            # System instructions tokens
            if request.system_instructions:
                breakdown.system_tokens += self._count_tokens(request.system_instructions)
            
            # Persona tokens
            if request.persona:
                breakdown.system_tokens += self._count_tokens(str(request.persona))
            
            # Profile tokens
            if request.profile:
                breakdown.system_tokens += self._count_tokens(str(request.profile))
            
            # Memory items tokens
            for item in request.memory_items:
                breakdown.memory_tokens += self._count_tokens(str(item))
            
            # Cortex intent tokens
            if request.cortex_intent:
                breakdown.system_tokens += self._count_tokens(str(request.cortex_intent))
            
            # Tool contracts tokens
            for contract in request.tool_contracts:
                breakdown.tool_tokens += self._count_tokens(str(contract))
            
            # Workflow context tokens
            if request.workflow_context:
                breakdown.system_tokens += self._count_tokens(str(request.workflow_context))
            
            # Provider capabilities tokens
            if request.provider_capabilities:
                breakdown.system_tokens += self._count_tokens(str(request.provider_capabilities))
            
            # Messages tokens
            for message in request.messages:
                breakdown.message_tokens += self._count_tokens(str(message))
            
            # Overhead tokens (safety margin)
            breakdown.overhead_tokens = 100
            
            # Calculate total
            total_tokens = (
                breakdown.system_tokens +
                breakdown.memory_tokens +
                breakdown.tool_tokens +
                breakdown.message_tokens +
                breakdown.overhead_tokens
            )
            
            breakdown.total_tokens = total_tokens
            
            return breakdown
        
        except Exception as e:
            raise TokenEstimateError(f"Failed to estimate tokens: {e}")
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in text (simplified implementation)."""
        if not text:
            return 0
        
        # Simple token estimation: split by whitespace and count words
        # In production, use tiktoken or similar library
        words = text.split()
        return len(words)
    
    def get_prompt_provenance(self, prompt_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Get provenance information for a prompt."""
        
        prompt = self.get_prompt(prompt_id, version)
        
        return {
            "prompt_id": prompt.prompt_id,
            "version": prompt.version,
            "name": prompt.name,
            "description": prompt.description,
            "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
            "status": prompt.status.value,
            "is_default": prompt.is_default,
            "hash": self._calculate_prompt_hash(prompt),
            "allowed_overrides": prompt.allowed_overrides,
            "metadata": prompt.metadata,
        }
    
    def _calculate_prompt_hash(self, prompt: PromptDefinition) -> str:
        """Calculate hash of prompt for provenance tracking."""
        
        # Create a deterministic representation of the prompt
        prompt_data = {
            "prompt_id": prompt.prompt_id,
            "version": prompt.version,
            "system_instructions": prompt.system_instructions,
            "persona_defaults": prompt.persona_defaults,
            "profile_defaults": prompt.profile_defaults,
            "tool_contracts": prompt.tool_contracts,
            "output_schema": prompt.output_schema,
            "token_budget": prompt.token_budget,
            "allowed_overrides": prompt.allowed_overrides,
        }
        
        # Sort keys for deterministic hash
        sorted_data = json.dumps(prompt_data, sort_keys=True)
        return hashlib.sha256(sorted_data.encode()).hexdigest()
    
    def validate_output_schema(self, prompt_id: str, output: Any, version: Optional[str] = None) -> Dict[str, Any]:
        """Validate output against prompt schema."""
        
        prompt = self.get_prompt(prompt_id, version)
        
        if not prompt.output_schema:
            return {
                "valid": True,
                "errors": [],
                "warnings": [],
            }
        
        errors = []
        warnings = []
        
        # Basic schema validation
        if not isinstance(output, dict):
            errors.append("Output must be a dictionary")
            return {"valid": False, "errors": errors, "warnings": warnings}
        
        # Check required fields
        required_fields = prompt.output_schema.get("required", [])
        for field in required_fields:
            if field not in output:
                errors.append(f"Missing required field: {field}")
        
        # Check field types
        properties = prompt.output_schema.get("properties", {})
        for field, field_schema in properties.items():
            if field in output:
                expected_type = field_schema.get("type")
                actual_value = output[field]
                
                if expected_type == "string" and not isinstance(actual_value, str):
                    errors.append(f"Field '{field}' must be string, got {type(actual_value).__name__}")
                elif expected_type == "integer" and not isinstance(actual_value, int):
                    errors.append(f"Field '{field}' must be integer, got {type(actual_value).__name__}")
                elif expected_type == "number" and not isinstance(actual_value, (int, float)):
                    errors.append(f"Field '{field}' must be number, got {type(actual_value).__name__}")
                elif expected_type == "boolean" and not isinstance(actual_value, bool):
                    errors.append(f"Field '{field}' must be boolean, got {type(actual_value).__name__}")
                elif expected_type == "array" and not isinstance(actual_value, list):
                    errors.append(f"Field '{field}' must be array, got {type(actual_value).__name__}")
                elif expected_type == "object" and not isinstance(actual_value, dict):
                    errors.append(f"Field '{field}' must be object, got {type(actual_value).__name__}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Global registry instance
_prompt_registry: Optional[PromptRegistry] = None


def get_prompt_registry() -> PromptRegistry:
    """Get or create the global prompt registry."""
    global _prompt_registry
    if _prompt_registry is None:
        _prompt_registry = PromptRegistry()
    return _prompt_registry


def register_prompt(prompt: PromptDefinition) -> PromptDefinition:
    """Register a prompt in the global registry."""
    registry = get_prompt_registry()
    return registry.register_prompt(prompt)


def get_prompt(prompt_id: str, version: Optional[str] = None) -> PromptDefinition:
    """Get a prompt from the global registry."""
    registry = get_prompt_registry()
    return registry.get_prompt(prompt_id, version)