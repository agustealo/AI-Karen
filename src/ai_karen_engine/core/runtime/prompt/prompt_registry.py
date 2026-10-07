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
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptDefinition,
    PromptVersion,
    PromptLifecycleStatus,
    PromptAssemblyRequest,
    PromptAssemblyResult,
    PromptTruncationEvent,
)
from ai_karen_engine.core.runtime.prompt.token_estimator import get_token_estimator

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
    
    total_tokens: int = 0
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
        self._ensure_builtin_prompts()
    
    @staticmethod
    def _storage_key(prompt_id: str, version: PromptVersion) -> str:
        return f"{prompt_id}@{version}"

    def _sync_default_flags(self, prompt_id: str) -> None:
        active_version = self._active_versions.get(prompt_id)
        for version, storage_key in self._version_index.get(prompt_id, {}).items():
            prompt = self._prompts.get(storage_key)
            if prompt is not None:
                prompt.is_default = version == active_version

    @staticmethod
    def _normalize_persisted_version(version_text: Any) -> str:
        """Normalize known legacy persisted versions at the storage boundary.

        Runtime prompt contracts remain strict semantic versions (vX.Y.Z).
        Older registries emitted vX or vX.Y; migrate only those deterministic
        legacy forms and reject anything ambiguous or malformed.
        """
        raw = str(version_text or "").strip()
        try:
            return str(PromptVersion.parse(raw))
        except ValueError:
            clean = raw.lower().lstrip("v")
            parts = clean.split(".") if clean else []
            if not parts or len(parts) > 2 or not all(part.isdigit() for part in parts):
                raise

            normalized_parts = [int(part) for part in parts]
            while len(normalized_parts) < 3:
                normalized_parts.append(0)
            return str(PromptVersion(*normalized_parts))

    @staticmethod
    def _parse_persisted_datetime(value: Any) -> Optional[datetime]:
        """Restore persisted ISO datetimes without weakening the runtime contract."""
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError(f"Invalid persisted datetime type: {type(value).__name__}")
        return datetime.fromisoformat(value)

    @staticmethod
    def _serialize_prompt(prompt: PromptDefinition) -> Dict[str, Any]:
        """Serialize a prompt definition with stable persistence types."""
        data = dict(prompt.__dict__)
        status = data.get("status")
        if isinstance(status, PromptLifecycleStatus):
            data["status"] = status.value
        for field_name in ("created_at", "deprecated_at"):
            value = data.get(field_name)
            if isinstance(value, datetime):
                data[field_name] = value.isoformat()
        return data

    @classmethod
    def _deserialize_prompt(cls, prompt_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize persistence-only types before constructing the strict contract."""
        data = dict(prompt_data)

        raw_status = data.get("status")
        if raw_status is not None and not isinstance(raw_status, PromptLifecycleStatus):
            data["status"] = PromptLifecycleStatus(str(raw_status))

        for field_name in ("created_at", "deprecated_at"):
            if field_name in data:
                data[field_name] = cls._parse_persisted_datetime(data[field_name])

        return data

    def _load_registry(self):
        """Load prompts from registry storage.

        Invalid individual prompt records are quarantined in memory so one
        stale legacy entry cannot take down PromptRuntime and therefore normal
        chat execution. Corrupt registry JSON or an invalid top-level schema
        still fails closed because the storage boundary itself is unreadable.
        """
        registry_file = self.registry_path / "registry.json"
        if not registry_file.exists():
            return

        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            prompt_records = data.get("prompts", [])
            if not isinstance(prompt_records, list):
                raise RegistryError("Prompt registry 'prompts' must be a list")

            skipped_records = 0
            migrated_records = 0

            # Load each prompt version as a distinct immutable registry entry.
            for index, prompt_data in enumerate(prompt_records):
                if not isinstance(prompt_data, dict):
                    skipped_records += 1
                    logger.warning(
                        "Ignoring invalid persisted prompt record index=%s: expected object",
                        index,
                    )
                    continue

                raw_prompt = dict(prompt_data)
                prompt_id = str(raw_prompt.get("prompt_id") or "")
                raw_version = str(raw_prompt.get("version") or "")
                try:
                    raw_prompt = self._deserialize_prompt(raw_prompt)
                    normalized_version = self._normalize_persisted_version(raw_version)
                    if normalized_version != raw_version:
                        raw_prompt["version"] = normalized_version
                        migrated_records += 1
                        logger.warning(
                            "Migrating legacy persisted prompt version prompt_id=%s from=%s to=%s",
                            prompt_id or "<unknown>",
                            raw_version,
                            normalized_version,
                        )

                    prompt = PromptDefinition(**raw_prompt)
                    version = prompt.parsed_version
                except (TypeError, ValueError) as exc:
                    skipped_records += 1
                    logger.warning(
                        "Ignoring invalid persisted prompt record index=%s "
                        "prompt_id=%s version=%s error=%s",
                        index,
                        prompt_id or "<unknown>",
                        raw_version or "<missing>",
                        exc,
                    )
                    continue

                storage_key = self._storage_key(prompt.prompt_id, version)
                self._prompts[storage_key] = prompt
                self._version_index.setdefault(prompt.prompt_id, {})[version] = (
                    storage_key
                )
                if prompt.is_default:
                    self._active_versions[prompt.prompt_id] = version

            for prompt_id, version_text in dict(
                data.get("active_versions") or {}
            ).items():
                try:
                    normalized_version = self._normalize_persisted_version(version_text)
                    version = PromptVersion.parse(normalized_version)
                except ValueError:
                    logger.warning(
                        "Ignoring invalid active prompt version %s=%s",
                        prompt_id,
                        version_text,
                    )
                    continue
                if version in self._version_index.get(prompt_id, {}):
                    self._active_versions[prompt_id] = version

            for prompt_id in self._version_index:
                if prompt_id not in self._active_versions:
                    versions = self._version_index[prompt_id]
                    if versions:
                        self._active_versions[prompt_id] = max(versions)
                self._sync_default_flags(prompt_id)

            logger.info(
                "Loaded %s prompt versions from registry migrated=%s quarantined=%s",
                len(self._prompts),
                migrated_records,
                skipped_records,
            )

        except RegistryError:
            raise
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
            raise RegistryError(f"Failed to load registry: {e}")
    
    def _ensure_builtin_prompts(self) -> None:
        """Install immutable built-in prompt contracts required by core runtime."""
        prompt_id = "karen.chat.default"
        if prompt_id in self._version_index:
            return

        prompt = PromptDefinition(
            prompt_id=prompt_id,
            version="v1.0.0",
            name="KAREN Default Chat",
            description="Canonical prompt contract for normal KAREN chat assembly.",
            system_instructions="",
            token_budget=4096,
            status=PromptLifecycleStatus.ACTIVE,
            is_default=True,
            metadata={
                "source": "builtin",
                "owner": "prompt_runtime",
                "purpose": "canonical_chat",
            },
        )
        version = prompt.parsed_version
        storage_key = self._storage_key(prompt.prompt_id, version)
        self._prompts[storage_key] = prompt
        self._version_index.setdefault(prompt.prompt_id, {})[version] = storage_key
        self._active_versions[prompt.prompt_id] = version
        self._sync_default_flags(prompt.prompt_id)

    def _save_registry(self):
        """Save prompts to registry storage."""
        registry_file = self.registry_path / "registry.json"
        
        try:
            data = {
                "prompts": [
                    self._serialize_prompt(prompt)
                    for prompt in self._prompts.values()
                ],
                "active_versions": {
                    prompt_id: str(version)
                    for prompt_id, version in self._active_versions.items()
                },
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
        
        # Add each semantic version as a distinct registry record.
        version = prompt.parsed_version
        storage_key = self._storage_key(prompt.prompt_id, version)
        self._prompts[storage_key] = prompt
        self._version_index.setdefault(prompt.prompt_id, {})[version] = storage_key

        # Set as active if marked as default. If this is the first version,
        # make it active so unversioned reads are deterministic.
        if prompt.is_default or prompt.prompt_id not in self._active_versions:
            self._active_versions[prompt.prompt_id] = version
        self._sync_default_flags(prompt.prompt_id)
        
        # Save registry
        self._save_registry()
        
        logger.info(f"Registered prompt: {prompt.prompt_id} v{prompt.version}")
        return prompt
    
    def get_prompt(self, prompt_id: str, version: Optional[str] = None) -> PromptDefinition:
        """Get a prompt definition by ID and optional version."""
        
        versions = self._version_index.get(prompt_id)
        if not versions:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")

        if version is None:
            resolved_version = self._active_versions.get(prompt_id) or max(versions)
        else:
            resolved_version = PromptVersion.parse(version)

        storage_key = versions.get(resolved_version)
        if storage_key is None:
            raise PromptNotFoundError(
                f"Version {version or resolved_version} not found for prompt {prompt_id}"
            )
        return self._prompts[storage_key]
    
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
        
        if prompt_id not in self._version_index:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")

        parsed_version = PromptVersion.parse(version)
        if prompt_id not in self._version_index or parsed_version not in self._version_index[prompt_id]:
            raise PromptNotFoundError(f"Version {version} not found for prompt {prompt_id}")
        
        # Update active version
        self._active_versions[prompt_id] = parsed_version
        
        self._sync_default_flags(prompt_id)
        
        # Save registry
        self._save_registry()
        
        logger.info(f"Set active version for {prompt_id}: {version}")
        return True
    
    def retire_prompt(self, prompt_id: str, version: Optional[str] = None) -> bool:
        """Retire a prompt or version."""
        
        if prompt_id not in self._version_index:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")

        if version is None:
            # Retire every stored semantic version for this prompt.
            for storage_key in self._version_index[prompt_id].values():
                self._prompts.pop(storage_key, None)
            self._version_index.pop(prompt_id, None)
            self._active_versions.pop(prompt_id, None)
            logger.info(f"Retired prompt: {prompt_id}")
        else:
            # Retire specific version
            parsed_version = PromptVersion.parse(version)
            if prompt_id in self._version_index and parsed_version in self._version_index[prompt_id]:
                storage_key = self._version_index[prompt_id].pop(parsed_version)
                self._prompts.pop(storage_key, None)

                # Update active version if this was the active one.
                if self._active_versions.get(prompt_id) == parsed_version:
                    remaining_versions = self._version_index[prompt_id]
                    if remaining_versions:
                        self._active_versions[prompt_id] = max(remaining_versions)
                    else:
                        self._active_versions.pop(prompt_id, None)
                if not self._version_index[prompt_id]:
                    self._version_index.pop(prompt_id, None)
                else:
                    self._sync_default_flags(prompt_id)

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
            
            # Proactive continuity candidates are evidence-backed possibilities,
            # not memory facts. Budget them separately from conversational history.
            for item in request.continuity_items:
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
        """Delegate token estimation to the canonical prompt estimator."""
        return get_token_estimator().estimate_text(text)
    
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