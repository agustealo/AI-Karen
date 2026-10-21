"""Canonical persisted persona contracts.

These models represent presentation preferences only. Authorization, provider
selection, memory access and tool execution remain runtime responsibilities.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class LanguageEnum(str, Enum):
    EN_US = "en_US"
    ENGLISH = "english"
    SPANISH = "spanish"
    FRENCH = "french"
    GERMAN = "german"
    CHINESE = "chinese"
    JAPANESE = "japanese"
    KOREAN = "korean"
    MULTILINGUAL = "multilingual"


class ToneEnum(str, Enum):
    FORMAL = "formal"
    CASUAL = "casual"
    FRIENDLY = "friendly"
    PROFESSIONAL = "professional"
    PLAYFUL = "playful"
    SERIOUS = "serious"
    TECHNICAL = "technical"


class VerbosityEnum(str, Enum):
    BRIEF = "brief"
    BALANCED = "balanced"
    MODERATE = "moderate"
    DETAILED = "detailed"
    VERBOSE = "verbose"


class MemoryWeightEnum(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Persona(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    system_prompt: str = ""
    default_tone: ToneEnum = ToneEnum.FRIENDLY
    default_verbosity: VerbosityEnum = VerbosityEnum.BALANCED
    default_language: LanguageEnum = LanguageEnum.EN_US
    memory_weight: MemoryWeightEnum = MemoryWeightEnum.MEDIUM
    context_window_size: int = Field(default=10, ge=1, le=100)
    domain_knowledge: List[str] = Field(default_factory=list)
    specialized_instructions: Optional[str] = None
    use_emoji: bool = False
    formality_level: float = Field(default=0.5, ge=0, le=1)
    creativity_level: float = Field(default=0.5, ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True
    is_system_persona: bool = False


class PersonaStyleOverride(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    persona_id: Optional[str] = None
    tone_override: Optional[ToneEnum] = None
    verbosity_override: Optional[VerbosityEnum] = None
    context_conditions: Dict[str, Any] = Field(default_factory=dict)


class ChatStyleContext(BaseModel):
    persona: Optional[Persona] = None
    style_override: Optional[PersonaStyleOverride] = None
    detected_user_tone: Optional[ToneEnum] = None
    detected_formality: Optional[float] = None
    detected_sentiment: Optional[float] = None
    conversation_id: Optional[str] = None
    turn_number: int = 1
    memory_persona_filter: Optional[str] = None
    memory_tone_filter: Optional[ToneEnum] = None

    def get_effective_tone(self) -> ToneEnum:
        if self.style_override and self.style_override.tone_override:
            return self.style_override.tone_override
        if self.persona:
            return self.persona.default_tone
        return self.detected_user_tone or ToneEnum.FRIENDLY

    def get_effective_verbosity(self) -> VerbosityEnum:
        if self.style_override and self.style_override.verbosity_override:
            return self.style_override.verbosity_override
        return self.persona.default_verbosity if self.persona else VerbosityEnum.BALANCED

    def get_effective_language(self) -> LanguageEnum:
        return self.persona.default_language if self.persona else LanguageEnum.EN_US

    def build_system_prompt(self) -> str:
        # This is presentation data, never an authority-bearing system prompt.
        return (
            f"Communication style: {self.get_effective_tone().value}; "
            f"detail: {self.get_effective_verbosity().value}; "
            f"language: {self.get_effective_language().value}."
        )


class PersonaMemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    tenant_id: str
    content: str
    persona_id: Optional[str] = None
    persona_name: Optional[str] = None
    conversation_id: Optional[str] = None
    tone_used: Optional[ToneEnum] = None
    verbosity_used: Optional[VerbosityEnum] = None
    memory_type: str = "conversation"
    importance_score: float = Field(default=0.5, ge=0, le=1)
    embedding_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserPersonaPreferences(BaseModel):
    revision: int = Field(default=0, ge=0)
    user_id: str
    tenant_id: str
    active_persona_id: Optional[str] = None
    default_tone: ToneEnum = ToneEnum.FRIENDLY
    default_verbosity: VerbosityEnum = VerbosityEnum.BALANCED
    default_language: LanguageEnum = LanguageEnum.EN_US
    enable_style_adaptation: bool = False
    adaptation_sensitivity: float = Field(default=0.5, ge=0, le=1)
    enable_persona_memory_filtering: bool = False
    cross_persona_memory_sharing: bool = False
    show_persona_selector: bool = True
    show_style_controls: bool = True
    enable_quick_style_adjustments: bool = True
    custom_personas: List[Persona] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


SYSTEM_PERSONAS = [
    Persona(id="assistant", name="Assistant", description="Helpful AI assistant", system_prompt="Helpful and clear responses.", default_tone=ToneEnum.FRIENDLY, default_verbosity=VerbosityEnum.MODERATE, is_system_persona=True),
    Persona(id="expert", name="Expert", description="Knowledgeable expert persona", system_prompt="Provide accurate, well-structured explanations.", default_tone=ToneEnum.PROFESSIONAL, default_verbosity=VerbosityEnum.DETAILED, is_system_persona=True),
    Persona(id="creative", name="Creative", description="Creative collaborator", system_prompt="Offer imaginative approaches grounded in facts.", default_tone=ToneEnum.PLAYFUL, default_verbosity=VerbosityEnum.MODERATE, is_system_persona=True),
]
