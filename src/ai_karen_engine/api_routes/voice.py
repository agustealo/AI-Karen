"""Authenticated read-only voice capability ingress.

A separate transcription endpoint will be enabled only after local audio
decoding, authorization, and bounded uploads are verified.
"""
from fastapi import APIRouter, Depends

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.voice_runtime import get_voice_runtime

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/capabilities")
async def get_voice_capabilities(
    user: UserData = Depends(get_current_user),
) -> dict[str, object]:
    """Expose verified engine health only to authenticated users."""
    capabilities = await get_voice_runtime().capabilities()
    return {
        "status": capabilities.status.value,
        "transcription_available": capabilities.transcription_available,
        "synthesis_available": capabilities.synthesis_available,
        "streaming_available": capabilities.streaming_available,
        "engine": capabilities.engine,
    }
