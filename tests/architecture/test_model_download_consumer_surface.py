from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / "src/ai_karen_engine/api_routes/models/model_orchestrator.py"
CONTROL = ROOT / "src/ai_karen_engine/core/model_runtime/model_download_control_service.py"
UI = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/components/settings/ModelDownloads.tsx"
)


def test_model_catalog_route_reuses_canonical_orchestrator() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    assert '@router.get("/catalog", response_model=List[ModelSummaryResponse])' in source
    assert 'get_orchestrator_service().list_models(' in source
    assert 'owner=""' in source
    assert 'search=(query or "").strip() or None' in source


def test_download_validation_resolves_metadata_even_with_explicit_channel() -> None:
    source = CONTROL.read_text(encoding="utf-8")

    assert "Metadata is consumer and policy truth" in source
    assert '"license": info.license' in source
    assert '"total_size": info.total_size' in source
    assert '"description": info.description' in source
    assert "if channel is None:" in source


def test_model_downloads_surface_is_guided_and_runtime_truthful() -> None:
    source = UI.read_text(encoding="utf-8")

    for token in (
        "Find a Model",
        "Automatic (recommended)",
        "Advanced install options",
        "validation?.allowed === true",
        "Local Model Health",
        "Retry download",
        "Remove {model.name || model.id}",
        "setInterval(() =>",
        "refreshJobsOnly",
    ):
        assert token in source

    assert "Search the live model catalog" in source
    assert "JSON.stringify(discoveryProgress" in source
    assert "Technical discovery details" in source
