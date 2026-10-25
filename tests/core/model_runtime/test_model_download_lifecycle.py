"""Durable model job lifecycle must not fabricate runtime readiness."""
from ai_karen_engine.core.model_runtime.model_download_lifecycle import (
    project_model_download_lifecycle,
)


def test_active_downloads_are_not_runtime_ready():
    for status in ("queued", "running", "paused", "pause_requested", "promoting"):
        result = project_model_download_lifecycle({"status": status})
        assert result["artifact_published"] is False
        assert result["selectable_in_chat"] is None
        assert result["runtime_healthy"] is None


def test_completed_download_only_confirms_acquisition():
    result = project_model_download_lifecycle({"status": "completed"})
    assert result["phase"] == "acquired"
    assert result["artifact_published"] is True
    assert result["artifact_verified"] is None
    assert result["runtime_registered"] is None
    assert result["runtime_loadable"] is None
    assert result["runtime_healthy"] is None
    assert result["selectable_in_chat"] is None


def test_unknown_or_failed_state_cannot_be_ready():
    for status in ("failed", "cancelled", "quarantined", "unexpected", None):
        result = project_model_download_lifecycle({"status": status})
        assert result["artifact_published"] is False
        assert result["selectable_in_chat"] is None
        assert result["readiness_authority"] == "runtime_registry_and_health_probe"


def test_untrusted_payload_cannot_assert_health():
    result = project_model_download_lifecycle({
        "status": "completed",
        "runtime_healthy": True,
        "selectable_in_chat": True,
        "artifact_verified": True,
    })
    assert result["runtime_healthy"] is None
    assert result["selectable_in_chat"] is None
    assert result["artifact_verified"] is None
