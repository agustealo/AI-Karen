"""Authenticated and bounded voice ingress. Runtime owns local transcription."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from math import isfinite
import json
import logging

from ai_karen_engine.core.voice.contracts import (
    AudioInput, MAX_AUDIO_BYTES, MAX_SYNTHESIS_TEXT_CHARS,
    SynthesisInput, VoiceContractError,
)

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
        "synthesis_engine": capabilities.synthesis_engine,
        "synthesis_voice_id": capabilities.synthesis_voice_id,
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
        if str(exc) == "local_transcription_unavailable":
            raise HTTPException(status_code=503, detail="local_transcription_unavailable") from None
        # RuntimeError is also raised by CTranslate2 and model decoders. An
        # unknown runtime failure must not masquerade as an unavailable model.
        logger.error("Local transcription inference failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503, detail="local_transcription_failed") from None
    except Exception as exc:
        # Exception messages and traceback locals can include decoder paths or
        # sensitive input metadata. Emit only an error class, never raw audio.
        logger.error("Local transcription inference failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503, detail="local_transcription_failed") from None
    return {"text": result.text, "engine": result.engine, "language": result.language}



async def _read_synthesis_input(request: Request) -> SynthesisInput:
    """One bounded, typed JSON ingestion path for all TTS engines."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="json_required")
    max_request_bytes = 12 * 1024
    declared = request.headers.get("content-length")
    if declared:
        try:
            size = int(declared)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_content_length") from None
        if size <= 0 or size > max_request_bytes:
            raise HTTPException(status_code=413, detail="synthesis_request_too_large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_request_bytes:
            raise HTTPException(status_code=413, detail="synthesis_request_too_large")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="invalid_synthesis_json") from None
    if not isinstance(payload, dict) or set(payload) - {"text", "voice_id"}:
        raise HTTPException(status_code=422, detail="invalid_synthesis_payload")
    text = payload.get("text")
    voice_id = payload.get("voice_id")
    if not isinstance(text, str) or len(text) > MAX_SYNTHESIS_TEXT_CHARS or (
        voice_id is not None and not isinstance(voice_id, str)
    ):
        raise HTTPException(status_code=422, detail="invalid_synthesis_payload")
    try:
        return SynthesisInput(text=text, voice_id=voice_id)
    except VoiceContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _speech_response(result: object) -> Response:
    """Cache-safe WAV playback response, independently of engine implementation."""
    return Response(
        content=result.audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "X-Karen-Voice-Engine": result.engine,
        },
    )


@router.get("/engines")
async def list_voice_engines(
    request: Request,
    user: UserData = Depends(get_current_user),
) -> dict[str, object]:
    """List backend-verified local speech engines permitted to this actor."""
    try:
        return await get_voice_runtime().engine_catalog(
            user, correlation_id=getattr(request.state, "correlation_id", None)
        )
    except VoiceContractError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    except Exception as exc:
        logger.error("Voice catalog unavailable", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503, detail="voice_catalog_unavailable") from None


@router.post("/engines/{engine_id}/synthesis")
async def synthesize_with_voice_engine(
    engine_id: str,
    request: Request,
    user: UserData = Depends(get_current_user),
) -> Response:
    """Thin ingress to the one VoiceRuntime and governed plugin executor."""
    runtime = get_voice_runtime()
    if runtime.synthesis_busy():
        raise HTTPException(
            status_code=429, detail="local_synthesis_busy",
            headers={"Retry-After": "1"},
        )
    # Runtime.synthesize_with_plugin is the single governed catalog/admission
    # authority. A second route-side probe doubles expensive Pocket cold-load
    # work and creates a check/use race before every bounded speech chunk.
    # Read only a strictly bounded payload, then delegate eligibility and
    # execution without caching or trusting a route-owned catalog.
    synthesis_input = await _read_synthesis_input(request)
    try:
        result = await runtime.synthesize_with_plugin(
            synthesis_input,
            engine_id=engine_id,
            principal=user,
            correlation_id=getattr(request.state, "correlation_id", None),
        )
    except VoiceContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        if str(exc) == "local_synthesis_busy":
            raise HTTPException(
                status_code=429, detail="local_synthesis_busy",
                headers={"Retry-After": "1"},
            ) from None
        if str(exc) == "local_synthesis_unavailable":
            raise HTTPException(status_code=503, detail="local_synthesis_unavailable") from None
        logger.error("Plugin synthesis failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503, detail="local_synthesis_failed") from None
    except Exception as exc:
        logger.error("Plugin synthesis failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503, detail="local_synthesis_failed") from None
    return _speech_response(result)


@router.post("/synthesis")
async def synthesize_voice(
    request: Request,
    user: UserData = Depends(get_current_user),
) -> Response:
    """Synthesize one bounded reply with a verified, explicitly enabled local engine.

    API ingress performs authentication and body validation only. It cannot
    choose a voice engine, download models or invoke browser-vendor services.
    """
    runtime = get_voice_runtime()
    capabilities = await runtime.capabilities()
    if not capabilities.synthesis_available:
        raise HTTPException(status_code=503, detail="local_synthesis_unavailable")
    if runtime.synthesis_busy():
        raise HTTPException(
            status_code=429,
            detail="local_synthesis_busy",
            headers={"Retry-After": "1"},
        )
    synthesis_input = await _read_synthesis_input(request)
    try:
        result = await runtime.synthesize(synthesis_input)
    except VoiceContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        if str(exc) == "local_synthesis_busy":
            raise HTTPException(
                status_code=429, detail="local_synthesis_busy",
                headers={"Retry-After": "1"},
            ) from None
        if str(exc) == "local_synthesis_unavailable":
            raise HTTPException(status_code=503, detail="local_synthesis_unavailable") from None
        logger.error(
            "Local synthesis failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503, detail="local_synthesis_failed") from None
    except Exception as exc:
        logger.error(
            "Local synthesis failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503, detail="local_synthesis_failed") from None
    return _speech_response(result)
