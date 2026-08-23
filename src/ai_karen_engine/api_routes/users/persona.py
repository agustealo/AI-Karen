"""
Persona API Routes
REST endpoints for managing personas, style controls, and user preferences
"""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.services.persona.persona_service import get_persona_service
from ai_karen_engine.core.persona.contracts import (
    LanguageEnum,
    PersonaStyleOverride,
    ToneEnum,
    VerbosityEnum,
)

router = APIRouter(tags=["personas"])
logger = logging.getLogger(__name__)


# Alias core dependency for convenience
get_current_user = bypass_user_context_func


# Request/Response Models


class CreatePersonaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    system_prompt: str = Field(..., min_length=10, max_length=2000)
    default_tone: ToneEnum = ToneEnum.FRIENDLY
    default_verbosity: VerbosityEnum = VerbosityEnum.BALANCED
    default_language: LanguageEnum = LanguageEnum.EN_US
    domain_knowledge: List[str] = Field(default_factory=list)
    specialized_instructions: Optional[str] = Field(None, max_length=1000)
    use_emoji: bool = False
    formality_level: float = Field(default=0.5, ge=0.0, le=1.0)
    creativity_level: float = Field(default=0.5, ge=0.0, le=1.0)


class UpdatePersonaRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    system_prompt: Optional[str] = Field(None, min_length=10, max_length=2000)
    default_tone: Optional[ToneEnum] = None
    default_verbosity: Optional[VerbosityEnum] = None
    default_language: Optional[LanguageEnum] = None
    domain_knowledge: Optional[List[str]] = None
    specialized_instructions: Optional[str] = Field(None, max_length=1000)
    use_emoji: Optional[bool] = None
    formality_level: Optional[float] = Field(None, ge=0.0, le=1.0)
    creativity_level: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None


class PersonaResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    system_prompt: str
    default_tone: ToneEnum
    default_verbosity: VerbosityEnum
    default_language: LanguageEnum
    domain_knowledge: List[str]
    specialized_instructions: Optional[str]
    use_emoji: bool
    formality_level: float
    creativity_level: float
    created_at: datetime
    updated_at: datetime
    is_active: bool
    is_system_persona: bool


class UpdatePreferencesRequest(BaseModel):
    active_persona_id: Optional[str] = None
    default_tone: Optional[ToneEnum] = None
    default_verbosity: Optional[VerbosityEnum] = None
    default_language: Optional[LanguageEnum] = None
    enable_style_adaptation: Optional[bool] = None
    adaptation_sensitivity: Optional[float] = Field(None, ge=0.0, le=1.0)
    enable_persona_memory_filtering: Optional[bool] = None
    cross_persona_memory_sharing: Optional[bool] = None
    show_persona_selector: Optional[bool] = None
    show_style_controls: Optional[bool] = None
    enable_quick_style_adjustments: Optional[bool] = None


class PreferencesResponse(BaseModel):
    user_id: str
    tenant_id: str
    active_persona_id: Optional[str]
    default_tone: ToneEnum
    default_verbosity: VerbosityEnum
    default_language: LanguageEnum
    enable_style_adaptation: bool
    adaptation_sensitivity: float
    enable_persona_memory_filtering: bool
    cross_persona_memory_sharing: bool
    show_persona_selector: bool
    show_style_controls: bool
    enable_quick_style_adjustments: bool
    updated_at: datetime


class SwitchPersonaRequest(BaseModel):
    persona_id: Optional[str] = None


class StyleAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class StyleAnalysisResponse(BaseModel):
    detected_tone: Optional[ToneEnum]
    formality_score: float
    sentiment_score: float
    complexity_score: float
    emotion_indicators: List[str]
    suggestions: List[str] = Field(default_factory=list)


class ChatContextRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    conversation_id: Optional[str] = None
    style_override: Optional[PersonaStyleOverride] = None
    turn_number: int = Field(default=1, ge=1)


class ChatContextResponse(BaseModel):
    system_prompt: str
    effective_tone: ToneEnum
    effective_verbosity: VerbosityEnum
    effective_language: LanguageEnum
    persona_name: Optional[str] = None
    memory_filters: Dict[str, Any] = Field(default_factory=dict)


# Persona Management Endpoints


@router.post("/", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(
    request: CreatePersonaRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PersonaResponse:
    """Create a new custom persona"""

    user_context = current_user
    persona_service = get_persona_service()

    try:
        persona = await persona_service.create_persona(
            user_id=user_context["user_id"],
            tenant_id=user_context["tenant_id"],
            persona_data=request.dict(),
        )

        return PersonaResponse(**persona.dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create persona")


@router.get("/", response_model=List[PersonaResponse])
async def list_personas(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[PersonaResponse]:
    """List all available personas for the current user"""

    user_context = current_user
    persona_service = get_persona_service()

    try:
        personas = await persona_service.list_available_personas(
            user_id=user_context["user_id"], tenant_id=user_context["tenant_id"]
        )

        return [PersonaResponse(**persona.dict()) for persona in personas]

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list personas")


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(
    persona_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PersonaResponse:
    """Get a specific persona by ID"""

    user_context = current_user
    persona_service = get_persona_service()

    try:
        persona = await persona_service.get_persona(
            persona_id=persona_id,
            user_id=user_context["user_id"],
            tenant_id=user_context["tenant_id"],
        )

        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")

        return PersonaResponse(**persona.dict())

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get persona")


@router.put("/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: str,
    request: UpdatePersonaRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PersonaResponse:
    """Update an existing persona"""

    user_context = current_user
    persona_service = get_persona_service()

    try:
        # Filter out None values
        updates = {k: v for k, v in request.dict().items() if v is not None}

        persona = await persona_service.update_persona(
            user_id=user_context["user_id"],
            tenant_id=user_context["tenant_id"],
            persona_id=persona_id,
            updates=updates,
        )

        return PersonaResponse(**persona.dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update persona")


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    persona_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Delete a custom persona"""

    user_context = current_user
    persona_service = get_persona_service()

    try:
        success = await persona_service.delete_persona(
            user_id=user_context["user_id"],
            tenant_id=user_context["tenant_id"],
            persona_id=persona_id,
        )

        if not success:
            raise HTTPException(status_code=404, detail="Persona not found")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete persona")


# User Preferences Endpoints


@router.get("/preferences/me", response_model=PreferencesResponse)
async def get_my_preferences(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PreferencesResponse:
    """Get current user's persona preferences."""

    user_id = current_user["user_id"]
    tenant_id = current_user.get("tenant_id", "default")
    persona_service = get_persona_service()

    try:
        preferences = await persona_service.get_user_preferences(
            user_id=user_id, tenant_id=tenant_id
        )

        return PreferencesResponse(**preferences.dict(exclude={"custom_personas"}))

    except Exception as exc:
        logger.error(f"Failed to load persona preferences: {exc}")
        raise HTTPException(status_code=500, detail="Failed to get preferences")


@router.put("/preferences/me", response_model=PreferencesResponse)
async def update_my_preferences(
    request: UpdatePreferencesRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PreferencesResponse:
    """Update current user's persona preferences."""

    user_id = current_user["user_id"]
    tenant_id = current_user.get("tenant_id", "default")
    persona_service = get_persona_service()

    try:
        updates = {
            key: value
            for key, value in request.dict().items()
            if value is not None
        }
        preferences = await persona_service.update_user_preferences(
            user_id=user_id,
            tenant_id=tenant_id,
            updates=updates,
        )

        return PreferencesResponse(**preferences.dict(exclude={"custom_personas"}))

    except Exception as exc:
        logger.error(f"Failed to update preferences: {exc}")
        raise HTTPException(status_code=500, detail="Failed to update preferences")


@router.post("/preferences/switch", response_model=PreferencesResponse)
async def switch_persona(
    request: SwitchPersonaRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PreferencesResponse:
    """Switch the active persona for the current user"""

    user_context = current_user
    persona_service = get_persona_service()

    try:
        preferences = await persona_service.switch_persona(
            user_id=user_context["user_id"],
            tenant_id=user_context["tenant_id"],
            persona_id=request.persona_id,
        )

        return PreferencesResponse(**preferences.dict(exclude={"custom_personas"}))

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to switch persona")


# Style Analysis and Context Endpoints


@router.post("/analyze-style", response_model=StyleAnalysisResponse)
async def analyze_style(
    request: StyleAnalysisRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> StyleAnalysisResponse:
    """Analyze the style of user text using NLP"""

    persona_service = get_persona_service()

    try:
        analysis = await persona_service.analyze_user_style(request.text)

        # Generate suggestions based on analysis
        suggestions = []
        if analysis.get("formality_score", 0.5) < 0.3:
            suggestions.append(
                "Consider using more formal language for professional contexts"
            )
        elif analysis.get("formality_score", 0.5) > 0.8:
            suggestions.append(
                "You could use more casual language for friendly conversations"
            )

        if analysis.get("complexity_score", 0.5) > 0.8:
            suggestions.append("Try breaking down complex ideas into simpler sentences")

        return StyleAnalysisResponse(
            detected_tone=analysis.get("detected_tone"),
            formality_score=analysis.get("formality_score", 0.5),
            sentiment_score=analysis.get("sentiment_score", 0.0),
            complexity_score=analysis.get("complexity_score", 0.5),
            emotion_indicators=analysis.get("emotion_indicators", []),
            suggestions=suggestions,
        )

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to analyze style")


@router.post("/chat-context", response_model=ChatContextResponse)
async def build_chat_context(
    request: ChatContextRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ChatContextResponse:
    """Build chat context with persona and style information"""

    user_context = current_user
    persona_service = get_persona_service()

    try:
        context = await persona_service.build_chat_context(
            user_id=user_context["user_id"],
            tenant_id=user_context["tenant_id"],
            message=request.message,
            conversation_id=request.conversation_id,
            style_override=request.style_override,
            turn_number=request.turn_number,
        )

        # Build memory filters
        memory_filters = {}
        if context.memory_persona_filter:
            memory_filters["persona_id"] = context.memory_persona_filter
        if context.memory_tone_filter:
            memory_filters["tone"] = context.memory_tone_filter.value

        return ChatContextResponse(
            system_prompt=context.build_system_prompt(),
            effective_tone=context.get_effective_tone(),
            effective_verbosity=context.get_effective_verbosity(),
            effective_language=context.get_effective_language(),
            persona_name=context.persona.name if context.persona else None,
            memory_filters=memory_filters,
        )

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to build chat context")


# Health and Status Endpoints


@router.get("/health")
async def persona_health_check():
    """Health check for persona service"""

    try:
        persona_service = get_persona_service()

        # Test basic functionality
        system_personas_count = len(
            [
                p
                for p in await persona_service.list_available_personas("test", "test")
                if p.is_system_persona
            ]
        )

        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "persona-service",
            "system_personas_available": system_personas_count,
            "nlp_analyzer_available": hasattr(
                persona_service.nlp_analyzer, "analyze_style"
            ),
        }

    except Exception as e:
        return {"status": "unhealthy", "error": str(e), "service": "persona-service"}


@router.get("/system-personas", response_model=List[PersonaResponse])
async def list_system_personas() -> List[PersonaResponse]:
    """List all built-in system personas (public endpoint)"""

    try:
        from ai_karen_engine.core.persona.contracts import SYSTEM_PERSONAS

        return [PersonaResponse(**persona.dict()) for persona in SYSTEM_PERSONAS]

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list system personas")
