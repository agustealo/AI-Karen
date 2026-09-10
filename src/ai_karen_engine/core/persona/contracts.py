"""
Persona contracts for AI Karen.
Provides basic persona definitions and contracts.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LanguageEnum(str, Enum):
    """Available language options for persona."""
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
    """Available tone options for persona."""
    FORMAL = "formal"
    CASUAL = "casual"
    FRIENDLY = "friendly"
    PROFESSIONAL = "professional"
    PLAYFUL = "playful"
    SERIOUS = "serious"


class VerbosityEnum(str, Enum):
    """Available verbosity options for persona."""
    BRIEF = "brief"
    BALANCED = "balanced"
    MODERATE = "moderate"
    DETAILED = "detailed"
    VERBOSE = "verbose"


@dataclass
class Persona:
    """System persona definition."""
    id: str
    name: str
    description: str
    tone: ToneEnum
    verbosity: VerbosityEnum
    instructions: List[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    enabled: bool = True


@dataclass
class ChatStyleContext:
    """Context for chat style adaptation."""
    tone: ToneEnum
    verbosity: VerbosityEnum
    formality_level: float = 0.5
    creativity_level: float = 0.5
    empathy_level: float = 0.5


@dataclass
class PersonaMemoryEntry:
    """Memory entry related to persona."""
    id: str
    persona_id: str
    user_id: str
    created_at: str
    context_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PersonaStyleOverride:
    """Override for persona style."""
    id: str
    persona_id: str
    tone_override: Optional[ToneEnum] = None
    verbosity_override: Optional[VerbosityEnum] = None
    context_conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserPersonaPreferences:
    """User preferences for personas."""
    user_id: str
    preferred_persona_id: str
    style_context: ChatStyleContext
    created_at: str
    updated_at: str
    custom_instructions: Optional[str] = None


# System personas
SYSTEM_PERSONAS = [
    Persona(
        id="assistant",
        name="Assistant",
        description="Helpful AI assistant",
        tone=ToneEnum.FRIENDLY,
        verbosity=VerbosityEnum.MODERATE,
        instructions=[
            "Be helpful and informative",
            "Provide clear and concise answers",
            "Be respectful and professional",
        ],
    ),
    Persona(
        id="expert",
        name="Expert",
        description="Knowledgeable expert persona",
        tone=ToneEnum.PROFESSIONAL,
        verbosity=VerbosityEnum.DETAILED,
        instructions=[
            "Provide expert-level insights",
            "Be thorough and accurate",
            "Cite relevant information when possible",
        ],
    ),
    Persona(
        id="creative",
        name="Creative",
        description="Creative and innovative persona",
        tone=ToneEnum.PLAYFUL,
        verbosity=VerbosityEnum.MODERATE,
        instructions=[
            "Think outside the box",
            "Be imaginative and innovative",
            "Suggest novel approaches",
        ],
    ),
]