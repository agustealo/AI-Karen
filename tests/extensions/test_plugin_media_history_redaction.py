"""Canonical PluginService must not retain private media bytes in history."""

from ai_karen_engine.services.plugin_service import (
    ExecutionStatus,
    PluginExecutionResult,
    PluginService,
)


def _service() -> PluginService:
    service = object.__new__(PluginService)
    service._history = []
    return service


def test_encoded_wav_is_returned_to_authorized_caller_but_not_cached():
    service = _service()
    result = PluginExecutionResult(
        request_id="authorized",
        plugin_name="pocket-tts",
        status=ExecutionStatus.COMPLETED,
        result={
            "engine": "pocket-tts",
            "voice_id": "alba",
            "content_type": "audio/wav",
            "audio_base64": "private-base64-voice-data",
        },
    )

    response = service._record_result(result)
    assert response is result
    assert response.result["audio_base64"] == "private-base64-voice-data"
    assert service.get_execution_history()[0] is not response
    cached = service.get_execution_history()[0]
    assert cached.result == {
        "engine": "pocket-tts",
        "voice_id": "alba",
        "content_type": "audio/wav",
        "media_payload_redacted": True,
    }
    assert cached.metadata["media_payload_redacted"] is True
    assert "private-base64-voice-data" not in str(service.get_execution_history())


def test_raw_audio_bytes_and_normal_tool_results_have_separate_history_rules():
    service = _service()
    audio = PluginExecutionResult(
        request_id="binary", plugin_name="speech-tts",
        status=ExecutionStatus.COMPLETED, result=b"private-wave-data",
    )
    ordinary = PluginExecutionResult(
        request_id="text", plugin_name="text-statistics",
        status=ExecutionStatus.COMPLETED, result={"word_count": 3},
    )

    assert service._record_result(audio).result == b"private-wave-data"
    assert service._record_result(ordinary).result == {"word_count": 3}
    cached = service.get_execution_history()
    assert cached[0].result == {"media_payload_redacted": True}
    assert cached[1].result == {"word_count": 3}
    assert b"private-wave-data" not in str(cached).encode()
