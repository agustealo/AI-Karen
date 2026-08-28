"""Persona and profile assembly contracts for PromptRuntime.

Persona is a presentation overlay only. It may shape wording and formatting, but
it is never an identity, policy, capability, routing, memory, workflow, or
persistence authority. PromptRuntime enforces this boundary even when legacy
callers provide broader persona dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


PERSONA_PRESENTATION_FIELDS = frozenset(
    {
        "style",
        "tone",
        "register",
        "verbosity",
        "warmth",
        "language_style",
        "formatting_preferences",
        "response_preferences",
    }
)

PERSONA_AUTHORITY_FIELDS = frozenset(
    {
        "system_prompt",
        "system_policy",
        "tenant_policy",
        "domain_instructions",
        "behavior_constraints",
        "identity",
        "identity_baseline",
        "self_model",
        "user_model",
        "relationship_model",
        "memory",
        "memory_scope",
        "memory_write",
        "provider",
        "provider_id",
        "model",
        "model_id",
        "tools",
        "tool_requirements",
        "plugins",
        "plugin_candidates",
        "workflow",
        "workflow_id",
        "capabilities",
        "required_capabilities",
        "permissions",
        "roles",
        "authorization",
        "runtime_policy",
        "reasoning_modes",
        "execution_topology",
        "persist",
        "persistence",
        "credentials",
        "auth_tokens",
        "api_keys",
        "internal_ids",
        "security_metadata",
    }
)


@dataclass(frozen=True)
class PersonaSanitizationResult:
    """Result of reducing persona input to presentation-only prompt data."""

    data: Dict[str, Any]
    rejected_fields: List[str] = field(default_factory=list)
    ignored_fields: List[str] = field(default_factory=list)


@dataclass
class PersonaPromptContext:
    """Typed presentation-only persona context.

    The legacy authority-bearing fields remain constructor-compatible while old
    callers migrate, but they are intentionally excluded from prompt data.
    """

    persona_id: str
    version: str
    style: str = ""
    tone: str = ""
    register: str = ""
    verbosity: str = ""
    warmth: str = ""
    language_style: str = ""
    formatting_preferences: List[str] = field(default_factory=list)
    response_preferences: List[str] = field(default_factory=list)

    # Legacy compatibility only. These values never enter the prompt through
    # PersonaPromptContext.get_prompt_data().
    system_prompt: str = ""
    domain_instructions: str = ""
    behavior_constraints: List[str] = field(default_factory=list)

    def get_prompt_data(self) -> Dict[str, Any]:
        """Return only presentation fields eligible for persona assembly."""
        result = PersonaAssemblyPolicy().sanitize_persona(self.__dict__)
        return result.data

    def get_rejected_fields(self) -> List[str]:
        """Expose authority-bearing legacy fields populated by the caller."""
        raw = self.__dict__
        return sorted(
            field_name
            for field_name in PERSONA_AUTHORITY_FIELDS
            if raw.get(field_name) not in (None, "", [], {}, ())
        )

    def is_safe_field(self, field_name: str) -> bool:
        """Return whether a field belongs to the presentation-only allowlist."""
        return field_name in PERSONA_PRESENTATION_FIELDS


class PersonaAssemblyPolicy:
    """Canonical prompt-boundary policy for persona presentation data."""

    def sanitize_persona(
        self,
        persona_data: Optional[Mapping[str, Any]],
    ) -> PersonaSanitizationResult:
        if not persona_data:
            return PersonaSanitizationResult(data={})

        data: Dict[str, Any] = {}
        rejected_fields: List[str] = []
        ignored_fields: List[str] = []

        for field_name, field_value in persona_data.items():
            if field_name in {"persona_id", "version", "enabled", "source", "scope"}:
                continue
            if field_name in PERSONA_AUTHORITY_FIELDS:
                if field_value not in (None, "", [], {}, ()):
                    rejected_fields.append(field_name)
                continue
            if field_name not in PERSONA_PRESENTATION_FIELDS:
                if field_value not in (None, "", [], {}, ()):
                    ignored_fields.append(field_name)
                continue
            normalized = self._normalize_value(field_name, field_value)
            if normalized not in (None, "", [], {}, ()):
                data[field_name] = normalized

        return PersonaSanitizationResult(
            data=data,
            rejected_fields=sorted(set(rejected_fields)),
            ignored_fields=sorted(set(ignored_fields)),
        )

    @staticmethod
    def _normalize_value(field_name: str, value: Any) -> Any:
        if field_name in {"formatting_preferences", "response_preferences"}:
            if not isinstance(value, (list, tuple)):
                return []
            normalized: List[str] = []
            for item in value:
                text = str(item).strip()
                if text and text not in normalized:
                    normalized.append(text)
            return normalized
        return str(value).strip() if value is not None else ""


@dataclass
class ProfilePromptContext:
    """Typed context for profile assembly into prompts."""

    profile_id: str
    user_id: str = ""

    # Display preferences (safe)
    theme: str = ""
    language: str = ""
    timezone: str = ""

    # Workflow preferences are descriptive prompt context only. They do not
    # authorize tools; RuntimePolicy remains the capability authority.
    default_workspace: str = ""
    preferred_tools: List[str] = field(default_factory=list)

    # Explicitly excluded from prompts
    credentials: Dict[str, Any] = field(default_factory=dict)
    security_metadata: Dict[str, Any] = field(default_factory=dict)
    internal_ids: Dict[str, Any] = field(default_factory=dict)
    private_data: Dict[str, Any] = field(default_factory=dict)

    prompt_safe_fields: List[str] = field(
        default_factory=lambda: [
            "theme",
            "language",
            "timezone",
            "default_workspace",
            "preferred_tools",
        ]
    )

    def get_prompt_data(self) -> Dict[str, Any]:
        """Get only prompt-safe data for assembly."""
        safe_data = {}
        for field_name in self.prompt_safe_fields:
            value = getattr(self, field_name, None)
            if value is not None:
                safe_data[field_name] = value
        return safe_data

    def is_safe_field(self, field_name: str) -> bool:
        """Check if a field is safe to include in prompts."""
        return field_name in self.prompt_safe_fields


class ProfileAssemblyPolicy:
    """Policy for assembling profile data into prompts."""

    def __init__(self) -> None:
        self.required_fields: List[str] = []
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
        if field_name in self.optional_fields:
            if not field_value:
                return False
            if isinstance(field_value, (list, dict)) and len(field_value) == 0:
                return False
        return True

    def sanitize_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize profile data for prompt assembly."""
        return {
            key: value
            for key, value in profile_data.items()
            if self.should_include(key, value)
        }


__all__ = [
    "PERSONA_AUTHORITY_FIELDS",
    "PERSONA_PRESENTATION_FIELDS",
    "PersonaAssemblyPolicy",
    "PersonaPromptContext",
    "PersonaSanitizationResult",
    "ProfileAssemblyPolicy",
    "ProfilePromptContext",
]
