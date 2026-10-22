"""Authenticated and bounded voice ingress. Runtime owns local transcription."""
from fastapi import APIRouter, Depends, HTTPException, Request
from math import isfinite
import logging

from ai_karen_engine.core.voice.contracts import AudioInput, MAX_AUDIO_BYTES, VoiceContractError

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.voice_runtime import get_voice_runtime

logger = logging.getLogger(__name__)
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


@router.post("/transcriptions")
async def transcribe_voice(
    request: Request,
    user: UserData = Depends(get_current_user),
) -> dict[str, object]:
    """Read bounded raw WAV audio, then delegate inference to VoiceRuntime.

    Duration header is a claimed value, not a trusted measurement; the local
    WAV decoder independently verifies the actual duration before inference.
    No recording is retained by this endpoint.
    """
    runtime = get_voice_runtime()
    capabilities = await runtime.capabilities()
    if not capabilities.transcription_available:
        raise HTTPException(status_code=503, detail="local_transcription_unavailable")
    # Avoid buffering uploads that cannot begin inference. This is advisory:
    # VoiceRuntime still rejects a race with another request after body read.
    if runtime.transcription_busy():
        raise HTTPException(
            status_code=429, detail="local_transcription_busy",
            headers={"Retry-After": "1"},
        )
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in ("audio/wav", "audio/x-wav"):
        raise HTTPException(status_code=415, detail="wav_audio_required")
    try:
        duration = float(request.headers.get("x-audio-duration-seconds", ""))
        if not isfinite(duration) or not 0 < duration <= 120:
            raise ValueError("invalid audio duration")
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422, detail="audio_duration_required") from None
    declared_size = request.headers.get("content-length")
    if declared_size:
        try:
            size = int(declared_size)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_content_length") from None
        if size <= 0 or size > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="audio_size_out_of_bounds")
    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="audio_size_out_of_bounds")
        chunks.append(chunk)
    try:
        metadata = AudioInput(media_type, total, duration)
    except VoiceContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        result = await runtime.transcribe(b"".join(chunks), metadata)
    except VoiceContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        if str(exc) == "local_transcription_busy":
            raise HTTPException(
                status_code=429,
                detail="local_transcription_busy",
                headers={"Retry-After": "1"},
            ) from None
        logger.warning("Local transcription runtime unavailable", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503, detail="local_transcription_unavailable") from None
    except Exception:
        # Do not return decoder/model internals or raw audio to clients/logs.
        logger.exception("Local transcription inference failed")
        raise HTTPException(status_code=503, detail="local_transcription_failed") from None
    return {"text": result.text, "engine": result.engine, "language": result.language}
