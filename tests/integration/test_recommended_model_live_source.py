"""Opt-in, real-network verification for Karen's configured first-run models.

Run with:
    KAREN_LIVE_MODEL_SOURCE_PROOF=1 PYTHONPATH=src pytest tests/integration/test_recommended_model_live_source.py -q

This test never downloads model weights or claims runtime inference readiness.
It uses the canonical source metadata resolver, not fabricated HF fixtures.
"""
from __future__ import annotations

import os
import re

import pytest

from ai_karen_engine.config.config_asset_loaders import load_model_download_recommendations
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    ModelOrchestratorService,
)

pytestmark = pytest.mark.skipif(
    os.getenv("KAREN_LIVE_MODEL_SOURCE_PROOF") != "1",
    reason="Opt in to live model-source verification explicitly",
)

IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)


@pytest.mark.asyncio
async def test_curated_model_metadata_live_source_and_revision(tmp_path) -> None:
    """Prove real source resolution, terms, and immutable revision per model."""
    entries = load_model_download_recommendations()["recommendations"]
    assert {entry["id"] for entry in entries} == {
        "spacy-english-core",
        "distilbert-semantic-encoder",
        "qwen3-lightweight-chat",
    }
    orchestrator = ModelOrchestratorService({
        "models_root": str(tmp_path / "models"),
        "registry_path": str(tmp_path / "registry.json"),
    })
    for entry in entries:
        info = await orchestrator.get_model_info(
            entry["model_id"], refresh_remote=True
        )
        assert info.model_id == entry["model_id"]
        assert info.revision and IMMUTABLE_REVISION.fullmatch(info.revision), (
            f"{entry['id']}: missing immutable source revision"
        )
        assert info.license and info.license.strip(), (
            f"{entry['id']}: source did not report reviewable license terms"
        )
        assert info.gated is False, (
            f"{entry['id']}: source unexpectedly requires gated access"
        )

        if entry["id"] == "spacy-english-core":
            # The canonical publisher validates a spaCy directory containing
            # config.cfg and meta.json; merely downloading a Python wheel is
            # insufficient to satisfy this contract.
            files = {str(file["path"]) for file in info.files}
            config_dirs = {
                name.removesuffix("/config.cfg") if name != "config.cfg" else ""
                for name in files
                if name == "config.cfg" or name.endswith("/config.cfg")
            }
            meta_dirs = {
                name.removesuffix("/meta.json") if name != "meta.json" else ""
                for name in files
                if name == "meta.json" or name.endswith("/meta.json")
            }
            assert config_dirs & meta_dirs, (
                "spaCy model source contains no publishable directory with "
                "config.cfg and meta.json; wheel-only snapshots require a "
                "governed extraction path before Install Essentials can work"
            )
