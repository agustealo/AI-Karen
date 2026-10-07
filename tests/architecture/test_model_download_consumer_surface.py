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
    assert '"gated": bool(info.gated)' in source
    assert '"resolved_revision": info.revision or revision or "main"' in source
    assert '"license_url": (' in source
    assert 'f"https://huggingface.co/{model_id}/tree/"' in source
    assert "if info.license or info.gated" in source
    assert "quote(str(info.revision or revision or 'main'), safe='')" in source
    assert '"total_size": info.total_size' in source
    assert '"description": info.description' in source
    assert "if channel is None:" in source
    assert "Model access metadata could not be verified" in source


def test_model_downloads_surface_is_guided_and_runtime_truthful() -> None:
    source = UI.read_text(encoding="utf-8")

    for token in (
        "Explore Model Catalog",
        "Automatic (recommended)",
        "Advanced install options",
        "validation?.allowed === true",
        "Discovery Health",
        "Retry download",
        "Remove {model.name || model.id}",
        "setInterval(() =>",
        "refreshJobsOnly",
    ):
        assert token in source

    assert "Search live Hugging Face metadata" in source
    assert "JSON.stringify(discoveryProgress" in source
    assert "Technical discovery details" in source
    assert "Model acquisition & inventory" in source
    assert "Download Safety & Policy" in source
    assert "Download Pipeline" in source
    assert "Installed Model Inventory" in source
    assert "Model Channels" in source


def test_recommended_models_are_config_driven_and_first_run_visible() -> None:
    config = (ROOT / "config_assets/model_download_recommendations.json").read_text(
        encoding="utf-8"
    )
    control = CONTROL.read_text(encoding="utf-8")
    route = ROUTE.read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")

    for model_id in (
        "spacy/en_core_web_sm",
        "distilbert/distilbert-base-uncased",
        "Qwen/Qwen3-0.6B",
    ):
        assert model_id in config

    assert '"core_spacy": ModelDownloadChannel(' in control
    assert 'if channel.id == "core_spacy":' in control
    assert '@router.get("/download/recommendations"' in route
    assert "Karen Recommended" in ui
    assert "Install Essentials" in ui
    assert "Model licenses are accepted per model" in ui
    assert "Review license" in ui
    assert "recommendedLicenseAcceptances" in ui
    assert "recommendationAcceptanceKey" in ui
    assert "item.resolved_revision || null" in ui
    assert "validation?.metadata.resolved_revision" in ui
    assert "validated_revision:" in ui
    assert "revision: null" in ui
    assert "validationGenerationRef" in ui
    assert "validationGeneration !== validationGenerationRef.current" in ui
    assert "(validation.requested_revision || '') === revision.trim()" in ui
    assert "reviewedRevision?: string | null" in ui
    assert "item.gated" in ui
    assert "(item.license || item.gated)" in ui
    assert "Restricted model access" in ui
    assert '"license_url"' in config
    assert 'item["license"] = info.license' in control
    assert 'item["resolved_revision"] = resolved_revision' in control
    assert 'item["metadata_verified"] = True' in control
    assert 'item["metadata_verified"] = False' in control
    assert "Verification unavailable" in ui
    assert "Access terms unavailable" in ui
    assert "I accept the ${String(validation.metadata.license)} license" in ui
    assert "I accept these required model access terms" in ui
    assert 'item["gated"] = bool(info.gated)' in control
    assert "if info.license or info.gated" in control
    assert 'f"https://huggingface.co/{model_id}/tree/"' in control


def test_model_library_root_is_backend_owned_and_user_configurable() -> None:
    control = CONTROL.read_text(encoding="utf-8")
    route = ROUTE.read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")

    assert "async def update_models_root(" in control
    assert "Model library folder cannot change while downloads are active" in control
    assert 'update_config(' in control
    assert '@router.put("/download/storage"' in route
    assert "Model Library Folder" in ui
    assert "KAREN_MODELS_ROOT" in ui


def test_legacy_thread_downloader_is_retired() -> None:
    assert not (
        ROOT
        / "src/ai_karen_engine/core/model_runtime/discovery/model_library_service.py"
    ).exists()
    assert not (
        ROOT
        / "src/ai_karen_engine/integrations/README_MODEL_DOWNLOAD_MANAGER.md"
    ).exists()


def test_distilbert_resolves_canonical_download_layout() -> None:
    source = (
        ROOT
        / "src/ai_karen_engine/core/intelligence/ml/encoders/distilbert.py"
    ).read_text(encoding="utf-8")

    assert 'local_root.glob(f"*--{model_name}/main")' in source


def test_model_runtime_telemetry_surfaces_existing_native_capabilities() -> None:
    control = CONTROL.read_text(encoding="utf-8")
    route = ROUTE.read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")

    assert "async def get_runtime_telemetry(" in control
    assert "get_platform_resource_service().snapshot" in control
    assert "ModelStorageMonitor(self.models_root)" in control
    assert '"max_concurrent_downloads": concurrency_limit' in control
    assert '"runtime_admin_required": True' in control

    assert '@router.get("/download/telemetry"' in route

    for token in (
        "Worker slots",
        "GPU / VRAM",
        "Storage allocation",
        "Admin governed",
        "remote code",
        "model_storage",
        "disk_usage",
    ):
        assert token in ui


def test_huggingface_license_metadata_uses_canonical_sdk_field() -> None:
    source = (
        ROOT
        / "src/ai_karen_engine/core/model_runtime/management/model_orchestrator_service.py"
    ).read_text(encoding="utf-8")

    assert 'getattr(remote, "card_data", None)' in source
    assert 'getattr(remote, "cardData", None)' in source
    assert 'license=card_data.get("license")' in source


def test_model_license_acceptance_revalidates_reviewed_revision() -> None:
    ui = UI.read_text(encoding="utf-8")
    control = CONTROL.read_text(encoding="utf-8")

    assert "reviewedRevision?: string | null" in ui
    assert "revisionForValidation" in ui
    assert "validateDownload(" in ui
    assert "validation?.metadata.resolved_revision" in ui
    assert 'request.get("validated_revision")' in control
    assert "validation_revision = reviewed_revision or revision" in control
    assert "Validated model revision changed before queueing" in control
    assert "install_path = self._build_install_path(" in control


def test_retry_preserves_install_alias_and_reviewed_revision() -> None:
    ui = UI.read_text(encoding="utf-8")

    assert "const retryInstallRevision = (job: DownloadJob)" in ui
    assert "revision: retryInstallRevision(job)" in ui
    assert "validated_revision: job.revision || null" in ui
    assert "job.channel_id === 'core_spacy'" in ui
