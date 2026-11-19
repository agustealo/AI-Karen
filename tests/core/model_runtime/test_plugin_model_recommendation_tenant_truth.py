"""Pinned plugin recommendations never inherit another tenant's model inventory."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.model_runtime import model_download_control_service as module
from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
    ModelDownloadPolicy,
)

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
PIN = "db04f0e653473e5c7333c69686ac92b7460b0c1d"

MODEL = {
    "id": "pocket-tts-english-18m-refl",
    "model_id": "kyutai/pocket-tts",
    "label": "Pocket TTS English",
    "purpose": "Local speech",
    "tier": "optional",
    "channel_id": "plugin_audio",
    "revision": PIN,
    "license": "CC-BY-4.0",
    "capabilities": ["audio"],
    "app_consumers": ["pocket-tts"],
}


@pytest.fixture
def control(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snapshot = tmp_path / "downloaded" / "pocket"
    snapshot.mkdir(parents=True)
    (snapshot / "tokenizer.model").write_bytes(b"fixture")

    service = object.__new__(ModelDownloadControlService)
    service.models_root = tmp_path
    service._policy = ModelDownloadPolicy(require_license_acceptance=False)
    service._orchestrator = SimpleNamespace(
        snapshot_registry_entry=AsyncMock(return_value={
            "install_path": str(snapshot),
        }),
        get_model_info=AsyncMock(return_value=SimpleNamespace(
            revision=PIN, license="CC-BY-4.0", gated=True,
        )),
    )

    receipts = [
        {
            "status": "completed",
            "tenant_id": TENANT_A,
            "model_id": MODEL["model_id"],
            "revision": PIN,
            "channel_id": "plugin_audio",
            "install_path": str(snapshot),
            "license_accepted": True,
            "trust_remote_code": False,
        }
    ]

    async def tenant_receipts(**kwargs):
        if kwargs["tenant_id"] == TENANT_A:
            return list(receipts)
        return []

    service.list_completed_model_installations = AsyncMock(side_effect=tenant_receipts)
    monkeypatch.setattr(
        module,
        "load_model_download_recommendations",
        lambda: {"schema_version": 1, "recommendations": [dict(MODEL)]},
    )
    return service, receipts, snapshot


@pytest.mark.asyncio
async def test_pocket_installed_requires_exact_current_tenant_license_receipt(control):
    service, _receipts, snapshot = control

    first = await service.get_recommendations(tenant_id=TENANT_A)
    assert first["recommendations"][0]["installed"] is True
    assert first["recommendations"][0]["install_path"] == str(snapshot)

    unrelated = await service.get_recommendations(tenant_id=TENANT_B)
    assert unrelated["recommendations"][0]["installed"] is False
    assert unrelated["recommendations"][0]["install_path"] is None
    assert unrelated["recommendations"][0]["status"] == "available"

    no_tenant = await service.get_recommendations()
    assert no_tenant["recommendations"][0]["installed"] is False
    assert no_tenant["recommendations"][0]["install_path"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field,bad_value", [
    ("license_accepted", False),
    ("trust_remote_code", True),
    ("status", "failed"),
    ("install_path", "/tmp/nonexistent-model-artifact"),
])
async def test_pocket_recommendations_reject_unusable_receipts(control, field, bad_value):
    service, receipts, _snapshot = control
    receipts[0][field] = bad_value
    result = await service.get_recommendations(tenant_id=TENANT_A)
    assert result["recommendations"][0]["installed"] is False


@pytest.mark.asyncio
async def test_pocket_recommendations_reject_symlink_and_outside_model_root(
    control, tmp_path: Path,
):
    service, receipts, snapshot = control
    external = tmp_path.parent / "outside-published"
    external.mkdir(exist_ok=True)
    (external / "tokenizer.model").write_bytes(b"fixture")
    receipts[0]["install_path"] = str(external)

    outside = await service.get_recommendations(tenant_id=TENANT_A)
    assert outside["recommendations"][0]["installed"] is False

    alias = tmp_path / "symlink-artifact"
    alias.symlink_to(snapshot, target_is_directory=True)
    receipts[0]["install_path"] = str(alias)
    symlink = await service.get_recommendations(tenant_id=TENANT_A)
    assert symlink["recommendations"][0]["installed"] is False


@pytest.mark.asyncio
async def test_recommendation_remote_metadata_failure_redacts_server_logs(
    control, caplog: pytest.LogCaptureFixture,
):
    """Secret-bearing source exceptions must never become telemetry messages."""
    import logging

    service, _receipts, _snapshot = control
    secret = "hf-source-secret-do-not-log"
    service._orchestrator.get_model_info.side_effect = RuntimeError(secret)

    with caplog.at_level(
        logging.INFO,
        logger="ai_karen_engine.core.model_runtime.model_download_control_service",
    ):
        result = await service.get_recommendations(tenant_id=TENANT_A)

    item = result["recommendations"][0]
    assert item["metadata_verified"] is False
    assert item["resolved_revision"] is None
    assert secret not in str(item.get("verification_error"))
    assert secret not in caplog.text
    assert "model_download_recommendation_metadata_unavailable" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
