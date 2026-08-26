"""
Persona and Profile assembly contracts for PromptRuntime.

Provides typed structures for persona and profile context with explicit
field eligibility and security boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PersonaPromptContext:
    """Typed context for persona assembly into prompts."""
    
    persona_id: str
    version: str
    system_prompt: str = ""
    style: str = ""
    domain_instructions: str = ""
    behavior_constraints: List[str] = field(default_factory=list)
    
    # Prompt safety
    prompt_safe_fields: List[str] = field(default_factory=lambda: [
        "system_prompt",
        "style", 
        "domain_instructions",
        "behavior_constraints",
    ])
    excluded_fields: List[str] = field(default_factory=lambda: [
        "credentials",
        "auth_tokens",
        "api_keys",
        "internal_ids",
        "security_metadata",
    ])
    
    def get_prompt_data(self) -> Dict[str, Any]:
        """Get only prompt-safe data for assembly."""
        return {
            k: v for k, v in self.__dict__.items()
            if k in self.prompt_safe_fields and not k.startswith("_")
        }
    
    def is_safe_field(self, field_name: str) -> bool:
        """Check if a field is safe to include in prompts."""
        return field_name in self.prompt_safe_fields


@dataclass
class ProfilePromptContext:
    """Typed context for profile assembly into prompts."""
    
    profile_id: str
    user_id: str = ""
    
    # Display preferences (safe)
    theme: str = ""
    language: str = ""
    timezone: str = ""
    
    # Workflow preferences (safe)
    default_workspace: str = ""
    preferred_tools: List[str] = field(default_factory=list)
    
    # Explicitly excluded from prompts
    credentials: Dict[str, Any] = field(default_factory=dict)
    security_metadata: Dict[str, Any] = field(default_factory=dict)
    internal_ids: Dict[str, Any] = field(default_factory=dict)
    private_data: Dict[str, Any] = field(default_factory=dict)
    
    # Assembly policy
    prompt_safe_fields: List[str] = field(default_factory=lambda: [
        "theme",
        "language",
        "timezone",
        "default_workspace",
        "preferred_tools",
    ])
    
    def get_prompt_data(self) -> Dict[str, Any]:
        """Get only prompt-safe data for assembly."""
        safe_data = {}
        for field in self.prompt_safe_fields:
            value = getattr(self, field, None)
            if value is not None:
                safe_data[field] = value
        return safe_data
    
    def is_safe_field(self, field_name: str) -> bool:
        """Check if a field is safe to include in prompts."""
        return field_name in self.prompt_safe_fields


class ProfileAssemblyPolicy:
    """Policy for assembling profile data into prompts."""
    
    def __init__(self) -> None:
        self.required_fields = []
        self.optional_fields = ["theme", "language", "timezone", "preferred_tools"]
        self.excluded_fields = [
            "credentials",
            "auth_tokens",
            "api_keys",
            "session_ids",
            "passwords",
            "security_questions",
            "internal_ids",
            "private_data",
        ]
    
    def should_include(self, field_name: str, field_value: Any) -> bool:
        """Determine if a profile field should be included in the prompt."""
        if field_name in self.excluded_fields:
            return False
        
        # Skip empty values for optional fields
        if field_name in self.optional_fields:
            if not field_value:
                return False
            if isinstance(field_value, (list, dict)) and len(field_value) == 0:
                return False
        
        return True
    
    def sanitize_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize profile data for prompt assembly."""
        return {
            k: v for k, v in profile_data.items()
            if self.should_include(k, v)
        }